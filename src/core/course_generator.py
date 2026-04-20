"""
Course Generator Pipeline
--------------------------
Transforms raw source text into a flat JSON state machine for the LMS layer.

Pipeline — two orchestrators, six phases:

  generate_course_async  (Phase 1 → 2a → 2b + 3 in parallel)
    Phase 1  — split_lessons:     Pure Python. Parses headers, weights paragraphs,
                                  splits/merges into lessons. Assigns topic_ids.
    Phase 2a — assign_modules:    Pure Python. Groups lessons into modules using
                                  a debt-tracking greedy algorithm.
    Phase 2b — name_modules:      Single LLM call. Names each module from its
                                  section headers + content snippets.
    Phase 3  — name_lessons:      Parallel LLM calls (one per page chunk).
                                  Names each lesson from its header + first paragraph.
    ↓ Pauses — awaits user module review ↓

  resume_after_review    (Phase 4 → 5 → 6)
    Phase 4  — name_modules:      Optional single LLM call. Re-names modules if
                                  user changed boundaries during review.
    Phase 5  — build_content:     Pure Python. Builds lesson_content (paragraph-level
                                  blocks with question counts; text lives in _master_index).
    Phase 6  — flatten:           Pure Python. Assembles flat state machine dict,
                                  injects checkpoints, synthesis nodes, and FINAL_TEST.

Classes:
    ProductionCourseGenerator — main class; holds adapter, model config, and all phases
    (PipelineAbortError and ParseCircuitBreaker are imported from course_generator_adapter)
"""

import asyncio
import json
import re
import time
import traceback
import random
import math
from pathlib import Path
from typing import Dict, List
from json_repair import repair_json

from src.api.course_generator_adapter import CourseGeneratorAdapter, PipelineAbortError, ParseCircuitBreaker
from src.utils.logger import get_logger

_log = get_logger("course")

# ---------------------------------------------------------------------------
# Module-level sentence / weight helpers
# Defined here (not on the class) so the render layer can import them without
# instantiating ProductionCourseGenerator.
# ---------------------------------------------------------------------------

_ABBREVIATIONS = {
    # Polish
    'm.in.', 'tzw.', 'np.', 'ok.', 'ul.', 'nr', 'al.', 'tel.',
    'str.', 'wg.', 'dot.', 'zw.', 'tj.', 'jw.', 'ww.', 'in.',
    'godz.', 'min.', 'maks.', 'tys.', 'mln.', 'mld.',
    'mgr.', 'dr.', 'prof.', 'inż.', 'lic.', 'red.', 'tłum.',
    # English
    'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.', 'vs.',
    'etc.', 'i.e.', 'e.g.', 'approx.', 'dept.', 'est.', 'fig.',
    'no.', 'vol.', 'pp.', 'ed.', 'rev.',
    'jan.', 'feb.', 'mar.', 'apr.', 'aug.', 'sep.', 'oct.', 'nov.', 'dec.',
    # Units and common
    'km.', 'cm.', 'mm.', 'kb.', 'mb.', 'gb.',
}


def split_sentences(text: str) -> list:
    """Split text into sentences using punctuation rules, skipping known abbreviations."""
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    sentences = []
    current = []
    words = text.split(' ')
    for i, word in enumerate(words):
        current.append(word)
        if re.search(r'[.!?]$', word):
            word_lower = word.lower()
            if re.match(r'^[.!?]+$', word):
                continue
            if re.match(r'^(\d+|[a-z])\.$', word) and len(current) == 1:
                continue
            if word.count('.') >= 2:
                continue
            if word_lower in _ABBREVIATIONS:
                continue
            if re.match(r'^[A-ZŁŚŹŻĆĄĘÓ]\.$', word):
                continue
            if i + 1 < len(words) and words[i + 1] and words[i + 1][0].islower():
                continue
            sentence = ' '.join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
    if current:
        remainder = ' '.join(current).strip()
        if remainder:
            sentences.append(remainder)
    return [s for s in sentences if s]


def paragraph_weight(text: str) -> int:
    """
    Estimate question count for a paragraph: ceil(sentences + commas × 0.45).
    Strips numeric/technical parentheses before counting commas.
    Returns 0 for empty text.
    """
    if not text:
        return 0
    sentences = split_sentences(text)
    text_no_numeric_parens = re.sub(r'\([^)]*[\d.][^)]*\)', '', text)
    return math.ceil(len(sentences) + text_no_numeric_parens.count(',') * 0.45)


class ProductionCourseGenerator:

    """
    Transforms source documents into a flat JSON state machine for the learning app.
    """
    _CIRCUIT_SERVER_MSG = "3+ server errors in 30 seconds"
    
    def __init__(
        self, 
        adapter: CourseGeneratorAdapter, 
        model_id: str = "deepseek/deepseek-chat",
        chunk_size: int = 1,
        language: str = "English",
        max_parallel: int = 10,
        title: str = ""
        
    ):
        self.adapter = adapter
        self.model_id = model_id
        self.language = language
        self.max_parallel = max_parallel   
        self.title = title
        self.master_index = {}
        self.q_overrides  = {}   # {pid: int} — user-set question count overrides from chunk review

    # ========================================
    # Content Weight System
    # ========================================

    def _split_sentences(self, text: str) -> list:
        """Delegate to module-level split_sentences."""
        return split_sentences(text)

    def _paragraph_weight(self, pid: str) -> int:
        """Estimate question count for a paragraph using the module-level formula."""
        text = self.master_index.get(pid, '')
        return paragraph_weight(text)
    
    # ========================================
    # LLM / API helpers
    # ========================================

    def _extract_json(self, text: str) -> tuple[str, bool]:
        """
        Extract the first complete JSON object or array from an LLM response.
        Returns (extracted_text, is_truncated).
        is_truncated=True means the opening bracket was found but never closed —
        do NOT pass to repair_json; retry the full LLM call instead.
        """
        text = text.strip()

        # Fenced code block — if the block is complete it cannot be truncated
        match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
        if match:
            return match.group(1), False

        idx_dict = text.find('{')
        idx_list = text.find('[')

        if idx_dict == -1 and idx_list == -1:
            # No brackets at all — treat as structural garbage, not truncation
            return text, False

        if idx_dict != -1 and (idx_list == -1 or idx_dict < idx_list):
            start_char, end_char = '{', '}'
            start = idx_dict
        else:
            start_char, end_char = '[', ']'
            start = idx_list

        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[start:i+1], False   # complete

        # Depth never reached 0 — bracket opened but never closed
        return text[start:], True   # truncated — do NOT repair
    
    def _prog_warn(self, message: str):
        """Send a warning line to the progress console."""
        print(f"[WARN]  {message}")
        if getattr(self, '_on_progress', None):
            self._on_progress('warning', message, {})

    def _prog_error(self, message: str):
        """Send an error line to the progress console."""
        _log.error(message)
        print(f"[ERROR]  {message}")
        if getattr(self, '_on_progress', None):
            self._on_progress('error', message, {})

    async def _parse_with_retry(
        self,
        prompt: str,
        max_tokens: int,
        context_label: str,
        expected_type: type,
        circuit_breaker: ParseCircuitBreaker,
        validator=None,  # callable(parsed) -> (bool, str) — True = valid
    ) -> any:
        """
        Call the LLM and parse JSON with up to 4 attempts.
        Attempt 4 is preceded by a 60-second sleeper (transient failure window).

        Truncation:  retry the full LLM call — repair_json is NOT used.
        Structural:  json.loads first, then repair_json as fallback.
        All 4 failed: raises PipelineAbortError — pipeline stops completely.
        """
        MAX_ATTEMPTS   = 4
        SLEEPER_BEFORE = 4      # attempt number that gets the 60s sleep before it
        SLEEPER_SECS   = 60

        for attempt in range(1, MAX_ATTEMPTS + 1):

            # ── Circuit breaker check ──────────────────────────────────────
            if circuit_breaker.is_open:
                if circuit_breaker.trip_reason == 'server_down':
                    msg = (f"🔴 {context_label} — provider appears unavailable "
                        f"({self._CIRCUIT_SERVER_MSG}). Pipeline aborted.")
                else:
                    msg = (f"🔴 {context_label} — model is not producing valid JSON "
                        f"reliably across multiple tasks. Consider switching models. "
                        f"Pipeline aborted.")
                self._prog_error(msg)
                raise PipelineAbortError(msg)

            # ── Abort flag (user-requested) ────────────────────────────────
            if getattr(self, '_abort_requested', False):
                msg = f"🛑 {context_label} — pipeline aborted by user."
                self._prog_error(msg)
                raise PipelineAbortError(msg)

            # ── Sleeper before final attempt ───────────────────────────────
            if attempt == SLEEPER_BEFORE:
                self._prog_warn(
                    f"⏳ {context_label} — 3 failed attempts. "
                    f"Waiting {SLEEPER_SECS}s before final try..."
                )
                await asyncio.sleep(SLEEPER_SECS)

            # ── LLM call ──────────────────────────────────────────────────
            try:
                raw = await self.adapter.generate_async(
                    prompt, self.model_id, max_tokens=max_tokens
                )
            except Exception as e:
                circuit_breaker.record_server_failure(context_label)
                if attempt < MAX_ATTEMPTS:
                    wait = 5 * attempt + random.uniform(0, 3)
                    self._prog_warn(
                        f"⚠️ {context_label} — server error attempt {attempt}/4: {e}. "
                        f"Retrying in {wait:.0f}s..."
                    )
                    await asyncio.sleep(wait)
                    continue
                msg = f"❌ {context_label} — server error after 4 attempts. Pipeline aborted."
                self._prog_error(msg)
                raise PipelineAbortError(msg) from e

            # ── Parse ──────────────────────────────────────────────────────
            extracted, is_truncated = self._extract_json(raw)

            if is_truncated:
                circuit_breaker.record_parse_failure(context_label)
                if attempt < MAX_ATTEMPTS:
                    wait = 5 * attempt + random.uniform(0, 3)
                    self._prog_warn(
                        f"⚠️ {context_label} — response truncated attempt {attempt}/4. "
                        f"Retrying in {wait:.0f}s..."
                    )
                    await asyncio.sleep(wait)
                    continue
                msg = f"❌ {context_label} — response truncated after 4 attempts. Pipeline aborted."
                self._prog_error(msg)
                raise PipelineAbortError(msg)

            # Not truncated — json.loads, then repair as fallback
            try:
                parsed = json.loads(extracted)
            except json.JSONDecodeError:
                try:
                    parsed = json.loads(repair_json(extracted))
                except Exception:
                    circuit_breaker.record_parse_failure(context_label)
                    if attempt < MAX_ATTEMPTS:
                        wait = 5 * attempt + random.uniform(0, 3)
                        self._prog_warn(
                            f"⚠️ {context_label} — JSON malformed attempt {attempt}/4. "
                            f"Retrying in {wait:.0f}s..."
                        )
                        await asyncio.sleep(wait)
                        continue
                    msg = f"❌ {context_label} — JSON unparseable after 4 attempts. Pipeline aborted."
                    self._prog_error(msg)
                    raise PipelineAbortError(msg)

            # ── Type coercion ──────────────────────────────────────────────
            if not isinstance(parsed, expected_type):
                if expected_type is list and isinstance(parsed, dict):
                    for key in ('paragraphs', 'items', 'lessons', 'modules', 'data'):
                        if isinstance(parsed.get(key), list):
                            parsed = parsed[key]
                            break
                    else:
                        circuit_breaker.record_parse_failure(context_label)
                        if attempt < MAX_ATTEMPTS:
                            self._prog_warn(
                                f"⚠️ {context_label} — unexpected type attempt {attempt}/4. Retrying..."
                            )
                            wait = 5 * attempt + random.uniform(0, 3)
                            await asyncio.sleep(wait)
                        msg = f"❌ {context_label} — wrong JSON type after 4 attempts. Pipeline aborted."
                        self._prog_error(msg)
                        raise PipelineAbortError(msg)

            if validator is not None:
                ok, reason = validator(parsed)
                if not ok:
                    circuit_breaker.record_parse_failure(context_label)
                    if attempt < MAX_ATTEMPTS:
                        wait = 5 * attempt + random.uniform(0, 3)
                        self._prog_warn(
                            f"⚠️ {context_label} — validation failed attempt {attempt}/4: "
                            f"{reason}. Retrying in {wait:.0f}s..."
                        )
                        await asyncio.sleep(wait)
                        continue
                    msg = f"❌ {context_label} — validation failed after 4 attempts: {reason}. Pipeline aborted."
                    self._prog_error(msg)
                    raise PipelineAbortError(msg)

            return parsed
    
    # ========================================
    # PHASE 1: Programmatic lesson splitting (no LLM)
    # ========================================

    def phase_1_split_lessons(self, pages_dict: Dict[str, str]) -> List[Dict]:
        """
        Pure Python. One lesson per paragraph — maximum question coverage focus.

        Each paragraph becomes its own lesson so the question generator receives
        a single focused unit of content. Weights are still calculated and stored
        so module assignment (phase 2) can group lessons by content density.

        Paragraphs under the same ## header are marked is_split=True with sequential
        part numbers so lesson naming still reflects they belong to the same section.
        Single-paragraph headers use is_split=False.

        Never mixes two different ## headers into one lesson.
        Returns flat list of lesson dicts ready for topic_id assignment.
        """
        sorted_pages = sorted(pages_dict.items(), key=lambda x: int(x[0].split('_')[1]))

        # ── First pass: collect header groups ─────────────────────────────
        header_groups = []  # [{header, pids, page_key}, ...]
        for page_key, page_text in sorted_pages:
            current_header = None
            current_pids   = []

            for line in page_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('##'):
                    if current_pids:
                        header_groups.append({
                            'header':   current_header or self.title,
                            'pids':     current_pids,
                            'page_key': page_key,
                        })
                    current_header = line.lstrip('#').strip()
                    current_pids   = []
                elif re.match(r'^\[P\d+\]', line):
                    pid = re.match(r'^\[(P\d+)\]', line).group(1)
                    current_pids.append(pid)

            if current_pids:
                header_groups.append({
                    'header':   current_header or self.title,
                    'pids':     current_pids,
                    'page_key': page_key,
                })

        # ── Second pass: emit one lesson per paragraph ─────────────────────
        all_lessons = []
        for group in header_groups:
            header   = group['header']
            pids     = group['pids']
            page_key = group['page_key']
            is_split = len(pids) > 1

            for part_num, pid in enumerate(pids, 1):
                weight = self._paragraph_weight(pid)
                all_lessons.append({
                    'header':     header,
                    'source_ids': [pid],
                    'weight':     weight,
                    'is_split':   is_split,
                    'part_num':   part_num if is_split else None,
                    'page_key':   page_key,
                })

        # ── Assign topic_ids ───────────────────────────────────────────────
        for idx, lesson in enumerate(all_lessons, 1):
            lesson['topic_id'] = f'L{idx:02d}'

        print(f"[OK] Phase 1a -- {len(all_lessons)} lessons from {len(sorted_pages)} chunks")
        return all_lessons
    
    # ========================================
    # PHASE 2a: Module assignment (Python, deterministic)
    # ========================================

    def phase_2a_assign_modules(self, lessons):
        """
        Pure Python. Groups lessons into modules using a debt-tracking greedy algorithm.

        Finds the number of modules N such that total_weight / N falls within
        MODULE_MIN=60 and MODULE_MAX=100. Header groups are never split across
        module boundaries. Overshoot debt is carried forward to keep subsequent
        modules from growing too large.

        Args:
            lessons (list): Flat lesson list from phase_1_split_lessons,
                            each dict must have 'weight' and 'header' keys.

        Returns:
            dict: {'modules': [{module_id, contains_lessons, total_weight}]}
        """
        MODULE_MIN = 60
        MODULE_MAX = 100

        total_weight = sum(l['weight'] for l in lessons)

        # Find N that gives the most even split within the 80-130 range
        best_n      = 1
        best_target = total_weight
        for n in range(1, len(lessons) + 1):
            target = total_weight / n
            if MODULE_MIN <= target <= MODULE_MAX:
                best_n      = n
                best_target = target
                break   # first N that fits is the largest target (most content per module)

        # If no N fits (very short course), use one module
        if best_target > MODULE_MAX:
            best_target = total_weight

        print(f"  Weight: {total_weight:.1f} total -> {best_n} modules x {best_target:.1f} target")

        # Group consecutive lessons by header (header groups never split)
        header_groups = []
        current_header, current_lessons = None, []
        for lesson in lessons:
            if lesson['header'] != current_header:
                if current_lessons:
                    header_groups.append(current_lessons)
                current_header  = lesson['header']
                current_lessons = [lesson]
            else:
                current_lessons.append(lesson)
        if current_lessons:
            header_groups.append(current_lessons)

        # Assign groups to modules, tracking debt from overshoots
        modules        = []
        current_groups = []
        current_weight = 0.0
        debt           = 0.0   # negative = this module owes content to the next

        for i, group in enumerate(header_groups):
            group_weight   = sum(l['weight'] for l in group)
            effective_target = best_target - debt

            # Flush when we hit or exceed the effective target
            # But never flush on the last group
            if (current_weight + group_weight > effective_target
                    and current_weight > 0
                    and i < len(header_groups) - 1):
                overshoot = current_weight - effective_target
                modules.append(current_groups)
                current_groups = []
                debt           = overshoot   # carry overshoot as debt into next module
                current_weight = 0.0

            current_groups.append(group)
            current_weight += group_weight

        if current_groups:
            modules.append(current_groups)

        # Build result
        result_modules = []
        for idx, module_groups in enumerate(modules, 1):
            flat = [l for group in module_groups for l in group]
            result_modules.append({
                'module_id':        f'M{idx:02d}',
                'contains_lessons': [l['topic_id'] for l in flat],
                'total_weight':     round(sum(l['weight'] for l in flat), 1),
            })

        print(f"[OK] Phase 2a -- {len(result_modules)} modules assigned")
        return {'modules': result_modules}

    # ========================================
    # PHASE 2b: Module naming (LLM, one call)
    # ========================================

    async def phase_2b_name_modules(self, module_map: Dict, lessons: List[Dict]) -> Dict:
        """
        Single LLM call. Names each module using its unique section headers
        and first sentence of the first paragraph in each header group.
        Returns {module_id: {module_title, module_subtitle}}.
        """
        lesson_by_id = {l['topic_id']: l for l in lessons}

        modules_for_prompt = []
        for mod in module_map['modules']:
            seen_headers = []
            snippets     = []
            for lid in mod['contains_lessons']:
                lesson = lesson_by_id.get(lid, {})
                h = lesson.get('header', '')
                if h and h not in seen_headers:
                    seen_headers.append(h)
                    first_pid  = lesson.get('source_ids', [None])[0]
                    first_text = self.master_index.get(first_pid, '') if first_pid else ''
                    sentences  = self._split_sentences(first_text)
                    if sentences:
                        snippets.append(sentences[0][:100])

            modules_for_prompt.append({
                'module_id': mod['module_id'],
                'headers':   seen_headers,
                'snippets':  snippets[:3],   # max 3 snippets per module
            })

        prompt = f"""You are naming modules for an educational course titled "{self.title}".

Each module entry shows its section headers and opening sentences.
Write a module_title (2–5 words) and module_subtitle (one sentence, 8–15 words).

OUTPUT LANGUAGE: {self.language}

INPUT:
{json.dumps(modules_for_prompt, ensure_ascii=False, indent=2)}

OUTPUT FORMAT (JSON array):
[
  {{
    "module_id": "M01",
    "module_title": "Short Module Title",
    "module_subtitle": "One sentence previewing the key concepts covered."
  }}
]

Return ONLY the JSON array."""

        expected_ids = {mod['module_id'] for mod in module_map['modules']}

        def validate_names(parsed):
            REQUIRED = {'module_id', 'module_title', 'module_subtitle'}
            for i, entry in enumerate(parsed):
                if not isinstance(entry, dict):
                    return False, f"entry {i} is not a dict"
                missing = REQUIRED - entry.keys()
                if missing:
                    return False, f"entry {i} missing fields: {missing}"
                if not entry.get('module_title', '').strip():
                    return False, f"entry {i} has empty module_title"
            covered = {e.get('module_id') for e in parsed}
            missing = expected_ids - covered
            if missing:
                return False, f"modules not named: {sorted(missing)}"
            return True, ""

        parsed = await self._parse_with_retry(
            prompt=prompt,
            max_tokens=2000,
            context_label="Phase 2b (Module Names)",
            expected_type=list,
            circuit_breaker=self._circuit_breaker,
            validator=validate_names,
        )

        result = {}
        for entry in parsed:
            mid = entry.get('module_id')
            if mid:
                result[mid] = {
                    'module_title':    entry.get('module_title', ''),
                    'module_subtitle': entry.get('module_subtitle', ''),
                }

        print(f"[OK] Phase 2b -- {len(result)} modules named")
        if getattr(self, '_on_progress', None):
            self._on_progress(2, f"Modules ready — {len(result)} modules", {'module_count': len(result)})
        return result
    
    # ========================================
    # PHASE 3: Naming Lessons
    # ========================================

    async def phase_3_name_lessons(self, lessons: List[Dict]) -> List[Dict]:
        """
        Phase 3: Name each lesson. One LLM call per chunk (lessons grouped by
        their page origin). Returns lessons with lesson_id, lesson_header,
        lesson_topic, lesson_sources. Part numbers appended in Python for splits.
        """
        print(f"\n[Phase 3] Naming {len(lessons)} lessons...")

        # Group lessons by their chunk (page_key) for batched naming calls
        from collections import defaultdict
        chunk_groups = defaultdict(list)
        for lesson in lessons:
            chunk_groups[lesson.get('page_key', 'all')].append(lesson)

        async def name_one_chunk(chunk_lessons: list) -> list:
            lines = []
            for lesson in chunk_lessons:
                first_pid = lesson.get('source_ids', [None])[0]
                first_text = self.master_index.get(first_pid, '') if first_pid else ''
                # Send full first paragraph as naming context
                lines.append(
                    f"Lesson {lesson['topic_id']} — header: \"{lesson['header']}\"\n"
                    f"{first_text}\n"
                )
            lessons_block = "\n---\n".join(lines)

            prompt = f"""You are naming lessons for an educational course.

COURSE TITLE: {self.title}
OUTPUT LANGUAGE: {self.language}

For each lesson below, write a lesson_title (5–8 words, specific to the content).
Do NOT include part numbers — those are added automatically.

{lessons_block}

Return ONLY a JSON array:
[
  {{"lesson_id": "L01", "lesson_title": "Specific title for this lesson"}}
]

Return only the JSON array."""

            expected_ids = {l['topic_id'] for l in chunk_lessons}

            def validate_names(parsed):
                if not parsed:
                    return False, "empty response"
                for i, entry in enumerate(parsed):
                    if not isinstance(entry, dict):
                        return False, f"entry {i} is not a dict"
                    if not entry.get('lesson_id'):
                        return False, f"entry {i} missing lesson_id"
                    if not entry.get('lesson_title', '').strip():
                        return False, f"entry {i} has empty lesson_title"
                covered = {e.get('lesson_id') for e in parsed}
                missing = expected_ids - covered
                if missing:
                    return False, f"lessons not named: {sorted(missing)}"
                return True, ""

            parsed = await self._parse_with_retry(
                prompt=prompt,
                max_tokens=2000,
                context_label=f"Phase 3 (naming {len(chunk_lessons)} lessons)",
                expected_type=list,
                circuit_breaker=self._circuit_breaker,
                validator=validate_names,
            )

            # Build title lookup and apply to lessons
            title_map = {e['lesson_id']: e['lesson_title'] for e in parsed}
            named = []
            for lesson in chunk_lessons:
                tid = lesson['topic_id']
                title = title_map.get(tid, lesson['header'])
                # Append part number in Python for split lessons
                if lesson.get('is_split') and lesson.get('part_num'):
                    title = f"{title} ({lesson['part_num']})"
                named.append({
                    'lesson_id':      tid,
                    'lesson_header':  lesson['header'],
                    'lesson_topic':   title,
                    'lesson_sources': lesson['source_ids'],
                })
                if getattr(self, '_on_progress', None):
                    self._on_progress('3_lesson', f"{tid}: {title}", {'lesson_id': tid, 'node_count': 0})
            return named

        semaphore = asyncio.Semaphore(self.max_parallel)
        async def name_chunk_limited(chunk_lessons):
            async with semaphore:
                return await name_one_chunk(chunk_lessons)

        results = await asyncio.gather(*[
            name_chunk_limited(chunk_lessons)
            for chunk_lessons in chunk_groups.values()
        ])

        structured = [lesson for group in results for lesson in group]
        # Restore original order
        order = {l['topic_id']: i for i, l in enumerate(lessons)}
        structured.sort(key=lambda l: order.get(l['lesson_id'], 999))

        print(f"[OK] Phase 3 complete -- {len(structured)} lessons named")
        if getattr(self, '_on_progress', None):
            self._on_progress(3, f"Lessons named — {len(structured)} total", {'lesson_count': len(structured)})
        return structured   
     
    # ========================================
    # PHASE 4: Name modules (single LLM call)
    # ========================================

    async def phase_4_name_modules(self, module_assignments: list, lesson_list: list) -> dict:
        """
        Generate module_title and module_subtitle for each module.
        Single API call — receives lesson titles per module as context.
        Returns {module_id: {module_title, module_subtitle}}
        """
        print(f"\n[Phase 4] Renaming {len(module_assignments)} modules after review...")

        # Build lesson lookup for title context
        lesson_by_id = {}
        for l in lesson_list:
            lesson_by_id[l['lesson_id']] = l.get('lesson_title') or l.get('lesson_topic', '')

        # Compact input: each module with its lesson titles as context
        modules_for_prompt = []
        for mod in module_assignments:
            titles = [lesson_by_id.get(lid, lid) for lid in mod['lesson_ids']]
            modules_for_prompt.append({
                'module_id': mod['module_id'],
                'suggested_title': mod.get('title', ''),
                'lesson_titles': titles
            })

        prompt = f"""You are naming modules for an educational course titled "{self.title}".

    Each module has a suggested title and a list of lesson titles it contains.
    Your task: write a precise module_title and a short module_subtitle for each.

    Rules:
    - module_title: 2–5 words, specific and descriptive, not generic ("Introduction" alone is too vague)
    - module_subtitle: one short sentence, 8–15 words, previewing the key concepts covered
    - Preserve the module_id exactly as given
    - Output language: {self.language}

    INPUT:
    {json.dumps(modules_for_prompt, ensure_ascii=False, indent=2)}

    OUTPUT FORMAT (JSON only):
    [
    {{
        "module_id": "M01",
        "module_title": "AC Circuit Fundamentals",
        "module_subtitle": "Covers impedance, phasors, and series RLC circuit analysis."
    }}
    ]

    Return ONLY raw JSON array."""

        expected_module_ids = {mod['module_id'] for mod in module_assignments}

        def validate_module_names(parsed):
            REQUIRED = {'module_id', 'module_title', 'module_subtitle'}
            for i, entry in enumerate(parsed):
                if not isinstance(entry, dict):
                    return False, f"entry {i} is not a dict"
                missing = REQUIRED - entry.keys()
                if missing:
                    return False, f"entry {i} missing fields: {missing}"
                if not entry.get('module_title', '').strip():
                    return False, f"entry {i} has empty module_title"

            covered = {entry.get('module_id') for entry in parsed}
            missing_ids = expected_module_ids - covered
            if missing_ids:
                return False, f"modules not named: {sorted(missing_ids)}"

            return True, ""

        parsed = await self._parse_with_retry(
            prompt=prompt,
            max_tokens=2000,
            context_label="Phase 4 (Module Names)",
            expected_type=list,
            circuit_breaker=self._circuit_breaker,
            validator=validate_module_names,
        )
        result = {}
        for entry in parsed:
            mid = entry.get('module_id')
            if mid:
                result[mid] = {
                    'module_title':    entry.get('module_title', ''),
                    'module_subtitle': entry.get('module_subtitle', '')
                }
        print(f"[OK] Phase 4 -- {len(result)} modules renamed")
        return result

    # ========================================
    # PHASE 5: Build content from facts (Pure Python — no LLM)
    # ========================================

    def phase_5_build_content(self, lesson_list: list, module_assignments: list, module_names: dict) -> list:
        """
        Build lesson_content from raw paragraphs.
        No nodes. Source paragraphs ARE the content.

        lesson_content → list of {id, questions} blocks (paragraph-level; text lives in _master_index)
        lesson_source is derived at runtime from _master_index + element fields — not stored.
        """
        print(f"\n[Phase 5] Building content for {len(lesson_list)} lessons...")

        # Build lesson_id → module lookup
        lesson_to_module = {}
        for mod in module_assignments:
            for lid in mod.get('lesson_ids', mod.get('contains_lessons', [])):
                lesson_to_module[lid] = mod['module_id']

        enriched = []
        for lesson in lesson_list:
            lesson_id     = lesson.get('lesson_id', '')
            lesson_header = lesson.get('lesson_header', '')
            lesson_title  = lesson.get('lesson_topic', lesson.get('lesson_title', lesson_id))
            sources       = lesson.get('lesson_sources', [])

            # Module title lookup
            mid          = lesson_to_module.get(lesson_id, '')
            module_title = module_names.get(mid, {}).get('module_title', '') if mid else ''

            # ── lesson_content: paragraph-level blocks with formula-driven question count
            blocks = []
            for pid in sources:
                text = self.master_index.get(pid, '').strip()
                if text and len(text) >= 40:
                    q_count = self.q_overrides.get(pid) or self._paragraph_weight(pid)
                    if q_count > 0:
                        blocks.append({"id": pid, "questions": q_count})

            lesson_content = blocks

            enriched.append({
                **lesson,
                'lesson_title':   lesson_title,
                'lesson_content': lesson_content,
            })

        print(f"[OK] Phase 5 -- Content built for {len(enriched)} lessons")
        return enriched
    
    # ========================================
    # PHASE 6: Transofrm into flat structure, add synthesis nodes and clean 
    # ========================================
    
    def phase_6_flatten(self, lesson_list: list, module_assignments: list, module_names: dict = None) -> dict:
        """
        Pure Python. Assembles the final flat state machine dict from enriched lessons.

        Beyond placing lessons in order, this phase also:
            - Injects module_checkpoint entries (mid-module review nodes) for modules
              with 8+ lessons, using cumulative children up to that point.
            - Appends a module_synthesis entry at the end of every module,
              referencing all lessons in that module as children.
            - Adds a FINAL_TEST sentinel entry as the last node.
            - Wires 'next' pointers across the entire sequence including
              checkpoints, syntheses, and cross-module transitions.
            - Embeds _master_index as a top-level key for downstream use.

        Args:
            lesson_list (list):        Enriched lesson dicts from phase_5_build_content.
            module_assignments (list): [{module_id, title, lesson_ids[]}] from module review.
            module_names (dict):       {module_id: {module_title, module_subtitle}}
                                       from phase_4_name_modules. Optional — falls back
                                       to module title from module_assignments.

        Returns:
            dict: Flat state machine keyed by element ID (lesson_id, checkpoint_id,
                  synthesis_id, 'FINAL_TEST', '_master_index').
        """

        print("\n[Phase 6] Building state machine...")
        module_names = module_names or {}
        flat_db = {}

        # ── 1. Build lesson lookup ───────────────────────────────────────────────
        lesson_by_id = {l['lesson_id']: l for l in lesson_list}

        # ── 2. Expand module assignments ─────────────────────────────────────────
        expanded_modules = []
        for mod in module_assignments:
            mod_lessons = []
            for lid in mod.get('lesson_ids', mod.get('contains_lessons', [])):
                if lid in lesson_by_id:
                    mod_lessons.append(lesson_by_id[lid])
            expanded_modules.append({
                'module_id': mod['module_id'],
                'title':     mod.get('title', mod['module_id']),
                'lessons':   mod_lessons
            })

        # ── 3. Pre-collect first lesson ID per module (for synthesis next links) ─
        module_first_ids = [
            mod['lessons'][0]['lesson_id'] if mod['lessons'] else None
            for mod in expanded_modules
        ]

        # ── 4. Checkpoint injection logic ────────────────────────────────────────
        # Returns ordered list of ('lesson', lesson_dict) | ('checkpoint', cp_dict)
        def inject_checkpoints(module_id, lessons):
            n = len(lessons)
            if n >= 14:
                positions = {math.floor(n / 3) - 1, math.floor(2 * n / 3) - 1}
            elif n >= 8:
                positions = {math.floor(n / 2) - 1}
            else:
                positions = set()

            result = []
            cp_num = 1
            for i, lesson in enumerate(lessons):
                result.append(('lesson', lesson))
                if i in positions:
                    # Option B: cumulative — all lessons from module start up to here
                    cp_children = [l['lesson_id'] for kind, l in result if kind == 'lesson']
                    result.append(('checkpoint', {
                        '_cp_id':       f"{module_id}-CP{cp_num}",
                        '_cp_children': cp_children,
                        '_cp_num':      cp_num
                    }))
                    cp_num += 1
            return result

        # ── 5. Build flat_db ──────────────────────────────────────────────────────
        for m_idx, mod in enumerate(expanded_modules):
            module_id = mod['module_id']
            m_info       = module_names.get(module_id, {})
            module_title    = m_info.get('module_title')    or mod['title']
            module_subtitle = m_info.get('module_subtitle') or ''
            lessons = mod['lessons']

            if not lessons:
                continue

            module_next = module_first_ids[m_idx + 1] if m_idx < len(expanded_modules) - 1 else 'FINAL_TEST'
            synthesis_id  = f"{module_id}-SYNTHESIS"
            all_lesson_ids = [l['lesson_id'] for l in lessons]

            sequence = inject_checkpoints(module_id, lessons)
            flat_ids = [
                item['lesson_id'] if kind == 'lesson' else item['_cp_id']
                for kind, item in sequence
            ]

            for seq_idx, (kind, item) in enumerate(sequence):
                next_id = flat_ids[seq_idx + 1] if seq_idx < len(sequence) - 1 else synthesis_id

                if kind == 'lesson':
                    lid = item['lesson_id']
                    flat_db[lid] = {
                        "module_id":       module_id,
                        "module_title":    module_title,
                        "module_subtitle": module_subtitle,
                        "lesson_header":   item.get('lesson_header', ''),
                        "lesson_title":    item.get('lesson_title') or item.get('lesson_topic', lid),
                        "lesson_content":  item.get('lesson_content', ''),
                        "source_ids":      item.get('lesson_sources', []),
                        "type": "lesson",
                        "next": next_id
                    }
                else:
                    cp_id = item['_cp_id']
                    flat_db[cp_id] = {
                        "module_id":       module_id,
                        "module_title":    module_title,
                        "module_subtitle": module_subtitle,
                        "lesson_title":    f"Checkpoint {item['_cp_num']}: {module_title}",
                        "type":            "module_checkpoint",
                        "children_ids":    item['_cp_children'],
                        "next":            next_id
                    }

            flat_db[synthesis_id] = {
                "module_id":       module_id,
                "module_title":    module_title,
                "module_subtitle": module_subtitle,
                "lesson_title":    f"Module Summary: {module_title}",
                "type":            "module_synthesis",
                "children_ids":    all_lesson_ids,
                "next":            module_next
            }

        flat_db["FINAL_TEST"] = {
            "lesson_title": "Final Test",
            "type":         "final_test",
            "next":         None
        }

        flat_db["_master_index"] = self.master_index

        lesson_count     = sum(1 for v in flat_db.values() if isinstance(v, dict) and v.get('type') == 'lesson')
        checkpoint_count = sum(1 for v in flat_db.values() if isinstance(v, dict) and v.get('type') == 'module_checkpoint')
        print(f"[OK] Phase 6 -- {lesson_count} lessons, {checkpoint_count} checkpoints ({len(flat_db)} total entries)")
        return flat_db
    
    # ========================================
    # ORCHESTRATOR MACHINE: Run all phases in sequence with progress reporting
    # ========================================
    
    async def generate_course_async(
        self,
        title: str,
        pages_dict: Dict[str, str],
        master_index: Dict[str, str] = None,
        on_progress = None
    ) -> Dict:
        """
        First orchestrator. Runs phases 1 through 3, then pauses for user review.

        Executes phase_1_split_lessons, phase_2a_assign_modules, then
        phase_2b_name_modules and phase_3_name_lessons in parallel. Saves
        debug snapshots to data/debug/ after each phase. Returns without
        writing the final course file — the pipeline pauses here so the user
        can inspect and adjust module boundaries before continuing.

        Args:
            title (str):                    Course title, used in LLM prompts and debug filenames.
            pages_dict (Dict[str, str]):    Page-keyed chunks from the render layer
                                            (e.g. {'page_1': '[P001] text...', ...}).
            master_index (Dict[str, str]):  Paragraph ID → raw text lookup built externally.
            output_path (str):              Not used in this orchestrator — reserved for
                                            resume_after_review.
            on_progress (callable):         Optional callback(step, msg, data) for UI
                                            progress reporting.

        Returns:
            dict on success:  {'success': True, 'status': 'awaiting_module_review',
                               'lesson_list': [...], 'module_suggestion': {...}}
            dict on failure:  {'success': False, 'error': str}
        """
        
        self.master_index = master_index or {}
        self.title = title 
        
        # ── SET UP DEDICATED DEBUG DIRECTORY ──────────────────────
        debug_dir = Path(f"data/debug/")
        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[DEBUG] Files will be saved to: {debug_dir}")
        # ────────────────────────────────────────────────────────
        
        def report(step, msg, data=None):
            if on_progress:
                on_progress(step, msg, data or {})
            else:
                print(f"[{step}] {msg}")
        self._on_progress = on_progress 
        self._circuit_breaker = ParseCircuitBreaker()
        try:

            # Phase 1a is now synchronous Python — no await needed
            master_toc = self.phase_1_split_lessons(pages_dict)
            report(1, f"Document parsed — {len(master_toc)} lessons identified.", {'total_lessons': len(master_toc)})

            with open(debug_dir / "1_lessons.json", 'w', encoding='utf-8') as f:
                json.dump(master_toc, f, indent=2, ensure_ascii=False)

           # --- PHASE 2a: Python module assignment (instant) ---
            module_map = self.phase_2a_assign_modules(master_toc)
            modules = module_map.get('modules', [])
            total_weight = sum(l['weight'] for l in master_toc)
            avg_weight = total_weight / len(modules) if modules else 0
            avg_lessons = len(master_toc) / len(modules) if modules else 0
            report(2, f"{len(modules)} modules · {len(master_toc)} lessons · ~{avg_lessons:.0f} lessons/module · target weight {avg_weight:.0f}", 
                   {'module_count': len(modules), 'lesson_count': len(master_toc)})

            # --- PHASE 2b + 3: Module naming + Lesson naming (parallel LLM) ---
            report(3, "Finalizing syllabus details...")
            module_names_list, lessons = await asyncio.gather(
                self.phase_2b_name_modules(module_map, master_toc),
                self.phase_3_name_lessons(master_toc)
            )

            # Merge module names into module_map
            for mod in module_map['modules']:
                mid   = mod['module_id']
                names = module_names_list.get(mid, {})
                mod['title']    = names.get('module_title', mid)
                mod['subtitle'] = names.get('module_subtitle', '')

            # 💾 DEBUG
            with open(debug_dir / "2_modules.json", 'w', encoding='utf-8') as f:
                json.dump(module_map, f, indent=2, ensure_ascii=False)
            with open(debug_dir / "3_named_lessons.json", 'w', encoding='utf-8') as f:
                json.dump(lessons, f, indent=2, ensure_ascii=False)
            # st.warning("Pipeline paused for testing! Check your 1b_flat.json file.")
            # st.stop()

            print(f"[PAUSE] Awaiting module review -- {len(lessons)} lessons in {len(module_map.get('modules', []))} modules.")
            return {
                'success': True,
                'status': 'awaiting_module_review',
                'lesson_list': lessons,       
                'module_suggestion': module_map  
            }
            
        except Exception as e:
            _log.exception("generate_course_async failed: %s", e)
            print(f"[ERROR] CRITICAL ERROR: {e}")
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    async def resume_after_review(
        self,
        lesson_list: list,
        module_assignments: list,
        output_path: str,
        on_progress=None,
        modules_changed: bool = False
    ) -> dict:
        """
        Second orchestrator — runs after user confirms module structure.
        Called by show_module_review() in the render layer.
        """

        start_time = time.time()
        debug_dir = Path("data/debug/")
        self._on_progress = on_progress  
        self._circuit_breaker = ParseCircuitBreaker() 

        def report(step, msg):
            if on_progress:
                on_progress(step, msg)
            else:
                print(f"[resume/{step}] {msg}")

        try:
            # Phase 4: Name modules — single API call
            already_named = (
                not modules_changed and
                all(mod.get('title', '').strip() for mod in module_assignments)
            )

            if already_named:
                report('naming', "Module titles confirmed — skipping rename.")
                module_names = {
                    mod['module_id']: {
                        'module_title':    mod['title'],
                        'module_subtitle': mod.get('subtitle', ''),
                    }
                    for mod in module_assignments
                }
            else:
                report('naming', "Generating module titles...")
                module_names = await self.phase_4_name_modules(module_assignments, lesson_list)

            with open(debug_dir / "4_module_names.json", 'w', encoding='utf-8') as f:
                json.dump(module_names, f, indent=2, ensure_ascii=False)

            # Phase 5: Build content — pure Python
            report('building', "Building lesson content...")
            enriched = self.phase_5_build_content(lesson_list, module_assignments, module_names)

            with open(debug_dir / "5_enriched_lessons.json", 'w', encoding='utf-8') as f:
                json.dump(enriched, f, indent=2, ensure_ascii=False)

            # Phase 6: Flatten to state machine — pure Python
            report('flattening', "Assembling course structure...")
            flat_db = self.phase_6_flatten(enriched, module_assignments, module_names)

            # Save final JSON
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(flat_db, f, indent=2, ensure_ascii=False)

            elapsed = (time.time() - start_time) / 60
            lesson_count = sum(1 for v in flat_db.values() if isinstance(v, dict) and v.get('type') == 'lesson')

            report('done', f"Course ready — {lesson_count} lessons")
            return {
                'success':      True,
                'json_path':    output_path,
                'json_data':    flat_db,
                'time_elapsed': elapsed,
            }

        except Exception as e:
            _log.exception("resume_after_review failed: %s", e)
            print(f"[ERROR] Resume error: {e}")
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
        