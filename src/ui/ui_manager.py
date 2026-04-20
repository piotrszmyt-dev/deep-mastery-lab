import streamlit as st
from pathlib import Path

# ==========================================
# Theme Manager
# ==========================================

def get_theme_map():
    """
    Builds a map of available themes.
    Key = display name shown in the menu
    Value = path to the CSS file
    """
    # 1. Hardcoded defaults
    themes = {
        "Default Deep Mastery Lab": "assets/default.css"
    }

    # 2. Auto-discovery — scan assets/ for additional .css files
    assets_dir = Path("assets")
    if assets_dir.exists():
        for file in assets_dir.glob("*.css"):
            # Skip default.css — already registered above
            if file.name == "default.css":
                continue
            
            # Skip legacy style.css
            if file.name == "Streamlit.css":
                continue
            
            # Normalize path separators on Windows
            file_str = str(file).replace("\\", "/") 
            
            # Derive display name from filename, e.g. theme_dragon_ball.css → "Dragon Ball"
            pretty_name = file.stem.replace("theme_", "").replace("_", " ").title()
            
            # Skip if name already registered
            if pretty_name not in themes:
                themes[pretty_name] = file_str
            
    return themes

def load_active_theme():
    """
    Loads the active theme at app startup.
    Must be called immediately after st.set_page_config.
    """
    themes = get_theme_map()
    
    # 1. Default initialisation
    if "active_theme_name" not in st.session_state:
        st.session_state.active_theme_name = "Default Deep Mastery Lab"
        
    # 2. Resolve active theme
    active_name = st.session_state.active_theme_name
    
    if active_name not in themes:
        active_name = "Default Deep Mastery Lab"
        st.session_state.active_theme_name = active_name

    selected_file = themes.get(active_name)

    # 3. Inject theme CSS
    if selected_file is not None:
        path = Path(selected_file)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
            except Exception as e:
                print(f"[WARN] Can't load the theme {selected_file}: {e}")
        else:
            print(f"[WARN] Theme not found: {selected_file}")
    
    # 4. Always inject layout fixes last to override bugs in theme files
    layout_css = Path("src/ui/layout_fixes.css")
    if layout_css.exists():
        try:
            with open(layout_css, "r", encoding="utf-8") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
        except Exception as e:
            print(f"[WARN] Can't load layout fixes: {e}")

