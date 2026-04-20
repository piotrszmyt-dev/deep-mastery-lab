"""
Keyboard Shortcuts
==================
Injects a JavaScript listener into the parent Streamlit document.

Supported shortcuts:
- 1 / 2 / 3 / 4  →  Answer A / B / C / D
- a / b / c / d  →  Answer A / B / C / D  (case-insensitive)
- Enter          →  Primary action button (Continue / Verify / Start Test)
- r / R          →  Retake Test (all retry contexts)
- s / S          →  Skip to Next (SRS journey)
- Backspace      →  Go Back to Card / Return to Course
"""
import streamlit.components.v1 as components


def init_shortcuts():
    components.html(
        """
        <script>
        const doc = window.parent.document;

        const clickButtonExact = (text) => {
            const buttons = Array.from(doc.querySelectorAll('button'));
            const target = buttons.find(btn => btn.innerText.trim() === text);
            if (target) target.click();
        };

        const clickButtonContains = (text) => {
            const buttons = Array.from(doc.querySelectorAll('button'));
            const target = buttons.find(btn => btn.innerText.includes(text));
            if (target) target.click();
        };

        doc.onkeydown = function(e) {
            const activeTag = doc.activeElement ? doc.activeElement.tagName : '';
            if (activeTag === 'TEXTAREA' || activeTag === 'INPUT') return;

            if (e.key === 'Enter') {
                clickButtonContains('Verify Mastery');
                clickButtonContains('Repeat Mastery Test');
                clickButtonContains('Begin Final Test');
                clickButtonContains('Start Mini-Test');
                clickButtonContains('Continue Journey');
                clickButtonContains('Complete Journey');
                clickButtonContains('Go Back to Card');
                clickButtonContains('Start Next Batch');
                clickButtonContains('Back to SRS');
                clickButtonContains('Take Another Test');
                clickButtonContains('Finish');
            }

            if (e.key === 'j' || e.key === 'J') clickButtonContains('Begin Journey');
            if (e.key === 's' || e.key === 'S') clickButtonContains('Skip to Next');
            if (e.key === 'r' || e.key === 'R') {
                clickButtonContains('Retake Test');
                clickButtonContains('Retake:');
            }

            if (e.key === 'Backspace') {
                e.preventDefault();
                clickButtonContains('Go Back to Card');
                clickButtonContains('Return to Course');
            }

            if (e.key === '1') clickButtonExact('A');
            if (e.key === '2') clickButtonExact('B');
            if (e.key === '3') clickButtonExact('C');
            if (e.key === '4') clickButtonExact('D');

            // Prevent Streamlit's built-in shortcuts (e.g. C = clear cache) from firing
            if (['A', 'B', 'C', 'D'].includes(e.key.toUpperCase())) {
                e.preventDefault();
                clickButtonExact(e.key.toUpperCase());
            }
        };
        </script>
        """,
        height=0,
    )