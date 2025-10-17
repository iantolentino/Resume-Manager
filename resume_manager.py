#!/usr/bin/env python3
"""
Resume / Details Manager — A4 Canvas + One/Two-Column Preview + Section Separator + Two-Column PDF
Includes:
 - Personal details
 - Categories with entries (name, optional link, date). Dates default to today.
 - Safe JSON atomic writes with a local lock
 - Settings (global) for columns (1 or 2) and section separator (on/off)
 - Live HTML preview sized like A4; preview respects columns and separator settings
 - PDF export using reportlab when available; respects columns and separator settings
 - Flask web UI to manage data and settings

Run:
  pip install flask
  # optional for PDF:
  pip install reportlab
  python app.py
"""
from pathlib import Path
import json
import datetime
import tempfile
import os
import time
import threading
import shutil
import logging
import traceback
from typing import Dict, Any, List, Optional

# ----------------------------- Config -----------------------------
SAVE_PATH = Path("./resume_data.json")
SAVE_DIR = SAVE_PATH.parent
PDF_PATH = SAVE_DIR / "resume.pdf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
file_lock = threading.Lock()

# ----------------------- Storage Utilities ------------------------
def ensure_folder():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

def default_structure():
    return {
        "personal_details": {},
        "categories": {},
        "settings": {
            "columns": 2,     # default to 2 columns
            "separator": True # default: show horizontal separators
        }
    }

def atomic_save(data: dict, max_attempts: int = 8, retry_delay: float = 0.12):
    ensure_folder()
    temp_file = None
    with file_lock:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=str(SAVE_DIR),
                prefix="tmp_resume_", suffix=".json"
            ) as tmp:
                temp_file = Path(tmp.name)
                json.dump(data, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                try:
                    os.fsync(tmp.fileno())
                except Exception:
                    pass

            attempts = 0
            while True:
                try:
                    os.replace(str(temp_file), str(SAVE_PATH))
                    break
                except PermissionError as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        raise
                    time.sleep(retry_delay)
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

def load_data(retries: int = 6, retry_delay: float = 0.08) -> dict:
    ensure_folder()
    for attempt in range(retries):
        try:
            if not SAVE_PATH.exists():
                base = default_structure()
                atomic_save(base)
                return base
            with file_lock, open(SAVE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                # Ensure settings exist
                if "settings" not in raw:
                    raw["settings"] = default_structure()["settings"]
                if "personal_details" not in raw:
                    raw["personal_details"] = {}
                if "categories" not in raw:
                    raw["categories"] = {}
                return raw
        except (PermissionError, OSError, json.JSONDecodeError) as e:
            logging.warning("load_data attempt %d failed: %s", attempt + 1, e)
            if isinstance(e, json.JSONDecodeError):
                try:
                    backup = SAVE_DIR / f"corrupt_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    shutil.copy2(SAVE_PATH, backup)
                    logging.info("Backed up corrupt JSON to %s", backup)
                except Exception:
                    logging.exception("Failed to backup corrupt JSON")
                base = default_structure()
                atomic_save(base)
                return base
            time.sleep(retry_delay)
    logging.error("load_data failed after retries; returning empty structure.")
    return default_structure()

# -------------------------- CRUD Logic ----------------------------
def set_personal_details(details: Dict[str, Any]) -> None:
    data = load_data()
    norm = {
        "name": (details.get("name") or "").strip(),
        "email": (details.get("email") or "").strip(),
        "phone": (details.get("phone") or "").strip(),
        "address": (details.get("address") or "").strip(),
        "dob": (details.get("dob") or "").strip(),  # YYYY-MM-DD
        "summary": (details.get("summary") or "").strip(),
        "updated_at": datetime.date.today().isoformat(),
    }
    data["personal_details"] = norm
    atomic_save(data)

def get_personal_details() -> Dict[str, Any]:
    return load_data().get("personal_details", {})

def add_category(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    data = load_data()
    cats = data.setdefault("categories", {})
    if name in cats:
        return False
    cats[name] = []
    atomic_save(data)
    return True

def delete_category(name: str) -> bool:
    data = load_data()
    cats = data.get("categories", {})
    if name in cats:
        del cats[name]
        atomic_save(data)
        return True
    return False

def add_entry(category: str, name: str, link: Optional[str] = None, date: Optional[str] = None) -> bool:
    category = (category or "").strip()
    if not category:
        return False
    data = load_data()
    cats = data.setdefault("categories", {})
    if category not in cats:
        return False
    dt = (date or "").strip() or datetime.date.today().isoformat()
    entry = {
        "name": (name or "").strip(),
        "link": (link or "").strip() or None,
        "date": dt,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if not entry["name"]:
        return False
    cats[category].append(entry)
    atomic_save(data)
    return True

def delete_entry(category: str, index: int) -> bool:
    data = load_data()
    cats = data.get("categories", {})
    items = cats.get((category or "").strip())
    if not items:
        return False
    try:
        del items[index]
        atomic_save(data)
        return True
    except Exception:
        return False

# ----------------------- Settings Utilities -----------------------
def get_settings() -> dict:
    data = load_data()
    return data.get("settings", default_structure()["settings"])

def set_settings(new_settings: dict) -> None:
    data = load_data()
    settings = data.setdefault("settings", default_structure()["settings"])
    # sanitize
    columns = int(new_settings.get("columns", settings.get("columns", 2)))
    if columns not in (1, 2):
        columns = 2
    separator = bool(new_settings.get("separator", settings.get("separator", True)))
    settings["columns"] = columns
    settings["separator"] = separator
    atomic_save(data)

# -------------------------- PDF Export ---------------------------
def generate_pdf(output_path: Path) -> Optional[Path]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether, Flowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
    except Exception as e:
        logging.warning("reportlab not installed: %s", e)
        return None

    data = load_data()
    pd = data.get("personal_details", {})
    cats = data.get("categories", {})
    settings = data.get("settings", {"columns": 2, "separator": True})

    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=20, spaceAfter=6)
    H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12, spaceBefore=6, spaceAfter=4)
    N = ParagraphStyle('N', parent=styles['BodyText'], fontSize=10, spaceAfter=2)

    class HRLine(Flowable):
        def __init__(self, width, thickness=0.5, color=colors.HexColor('#e6e6e6')):
            super().__init__()
            self.width_val = width
            self.thickness = thickness
            self.color = color
            self.height = thickness + 2

        def wrap(self, availWidth, availHeight):
            return (self.width_val if self.width_val else availWidth, self.height)

        def draw(self):
            self.canv.setStrokeColor(self.color)
            self.canv.setLineWidth(self.thickness)
            w = self.width_val if self.width_val else self.canv._pagesize[0]
            self.canv.line(0, 0, w, 0)

    doc = BaseDocTemplate(str(output_path), pagesize=A4,
                          leftMargin=14*mm, rightMargin=14*mm,
                          topMargin=14*mm, bottomMargin=14*mm)

    frame_gap = 8*mm
    page_w, page_h = A4
    usable_w = page_w - doc.leftMargin - doc.rightMargin
    frame_h = page_h - doc.topMargin - doc.bottomMargin

    frames = []
    if settings.get("columns", 2) == 2:
        col_w = (usable_w - frame_gap) / 2
        x0 = doc.leftMargin
        frames = [
            Frame(x0, doc.bottomMargin, col_w, frame_h, id='col1', showBoundary=0),
            Frame(x0 + col_w + frame_gap, doc.bottomMargin, col_w, frame_h, id='col2', showBoundary=0),
        ]
    else:
        # one column spans full usable width
        col_w = usable_w
        frames = [Frame(doc.leftMargin, doc.bottomMargin, col_w, frame_h, id='col1', showBoundary=0)]

    doc.addPageTemplates(PageTemplate(id='ResumeTemplate', frames=frames))

    story: List[Any] = []

    # Header
    name = pd.get("name") or "Your Name"
    header_parts = [Paragraph(name, H1)]
    contact_items = []
    if pd.get("email"):
        contact_items.append(pd.get("email"))
    if pd.get("phone"):
        contact_items.append(pd.get("phone"))
    if pd.get("address"):
        contact_items.append(pd.get("address"))
    if pd.get("dob"):
        contact_items.append(f"DOB: {format_date(pd.get('dob',''))}")
    contact_line = " | ".join(contact_items)
    if contact_line:
        header_parts.append(Paragraph(contact_line, N))
    if pd.get("summary"):
        header_parts.append(Paragraph(pd["summary"], N))
    header_parts.append(Spacer(1, 6))
    story.append(KeepTogether(header_parts))

    # Categories
    first = True
    for cat, items in cats.items():
        # Add separator before section when requested (but not before first)
        if not first and settings.get("separator", True):
            story.append(Spacer(1, 4))
            story.append(HRLine(col_w, thickness=0.6))
            story.append(Spacer(1, 4))
        first = False

        story.append(Paragraph(cat, H2))
        for e in items:
            line = f"<b>{escape_html(e.get('name',''))}</b>"
            if e.get("date"):
                line += f" — {escape_html(format_date(e['date']))}"
            if e.get("link"):
                # show link as text (clickable when PDF viewer supports)
                line += f" — <font color='{colors.HexColor('#1a73e8')}'>{escape_html(e['link'])}</font>"
            story.append(Paragraph(line, N))
        story.append(Spacer(1, 4))

    try:
        doc.build(story)
    except Exception as e:
        logging.exception("Error building PDF: %s", e)
        return None
    return output_path

# --------------------------- Utils --------------------------------
def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def format_date(val: str, out_fmt: str = "%b %d, %Y") -> str:
    try:
        if not val:
            return ""
        datepart = val.split("T")[0]
        dt = datetime.datetime.strptime(datepart, "%Y-%m-%d")
        return dt.strftime(out_fmt)
    except Exception:
        return val

# ---------------------------- Flask UI -----------------------------
def run_flask():
    try:
        from flask import Flask, render_template_string, request, redirect, url_for, send_file, flash, get_flashed_messages
    except Exception:
        logging.info("Flask not installed. Install with: pip install flask")
        raise

    app = Flask(__name__)
    app.secret_key = "replace-this-with-a-random-secret-if-deploying"

    @app.template_filter("fmtdate")
    def jinja_fmtdate(value):
        return format_date(value)

    TEMPLATE = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Resume Manager</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root{
      --bg:#0f1724; --card:#0b1220; --muted:#98a0aa; --ink:#e6eef8; --accent:#58a6ff; --danger:#e11d48;
      --a4w:210mm; --a4h:297mm;
    }
    *{box-sizing:border-box}
    body{font-family:Inter, system-ui, -apple-system, 'Segoe UI', Roboto, Arial; margin:0; padding:18px; background:linear-gradient(180deg,#071021,#091227); color:var(--ink)}
    .container{max-width:1100px; margin:0 auto}
    .card{background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); padding:18px; border-radius:12px; box-shadow:0 6px 18px rgba(2,6,23,.6); margin-bottom:18px}
    h1{margin:0 0 12px}
    h3{margin:12px 0 8px}
    input[type=text], input[type=date], textarea, select{width:100%; padding:8px 10px; border:1px solid rgba(255,255,255,0.04); border-radius:8px; background:transparent; color:var(--ink)}
    textarea{min-height:80px}
    button{background:var(--accent); color:#041225; border:none; padding:8px 12px; border-radius:8px; cursor:pointer}
    button.secondary{background:#475569; color:#fff}
    button.danger{background:var(--danger); color:#fff}
    .row{display:flex; gap:12px; flex-wrap:wrap}
    .col{flex:1 1 280px}
    .muted{color:var(--muted); font-size:13px}
    .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px}
    .flash{padding:10px;border-radius:8px;margin:8px 0}
    .flash.success{background:#083d22;color:#a7f3d0}
    .flash.error{background:#4c0519;color:#fecaca}
    .preview-wrap{overflow:auto; max-height:75vh; padding:6px; border:1px dashed rgba(255,255,255,0.04); border-radius:12px; background:transparent}
    .a4{
      width: var(--a4w); min-height: var(--a4h);
      background:#fff; color:#111827;
      margin:0 auto; padding:18mm 16mm;
      box-shadow:0 3px 12px rgba(0,0,0,.08); border-radius:6px;
    }
    .a4 h2{margin:0 0 6px}
    .a4 .sub{color:#374151; font-size:11pt; margin-bottom:10px}
    .columns{ column-gap:12mm; column-fill:balance; }
    .section{break-inside:avoid; margin:0 0 10px}
    .section h4{margin:0 0 4px; padding-bottom:2px}
    .item{margin:3px 0; font-size:11pt}
    .item a{color:#1d4ed8; text-decoration:none}
    .top-actions{display:flex; gap:8px; align-items:center; flex-wrap:wrap}
    .settings-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:10px}
    .mini{font-size:13px;color:var(--muted)}
    label.inline{display:inline-flex;gap:8px;align-items:center}
    /* dynamic columns from settings */
    .columns.count-1 { column-count: 1; }
    .columns.count-2 { column-count: 2; }

    /* separator rule (visible in preview) */
    .section.separator { border-bottom: 1px solid #e6e6e6; padding-bottom: 6px; margin-bottom: 8px; }

    @media (max-width:980px){
      .a4{width:100%; min-height:400px; padding:18px}
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <h1>Resume Details Manager</h1>
      <div class="muted">Data file: {{ save_path }}</div>

      {% for msg, cat in flashes %}
        <div class="flash {{ 'error' if cat=='error' else 'success' }}">{{ msg }}</div>
      {% endfor %}

      <h3>Personal Details</h3>
      <form method="post" action="{{ url_for('save_personal') }}">
        <div class="row">
          <div class="col"><label>Name</label><input type="text" name="name" value="{{ pd.get('name','') }}"></div>
          <div class="col"><label>Email</label><input type="text" name="email" value="{{ pd.get('email','') }}"></div>
          <div class="col"><label>Phone</label><input type="text" name="phone" value="{{ pd.get('phone','') }}"></div>
        </div>
        <div class="row" style="margin-top:10px">
          <div class="col"><label>Address</label><input type="text" name="address" value="{{ pd.get('address','') }}"></div>
          <div class="col"><label>Date of Birth</label><input type="date" name="dob" value="{{ pd.get('dob','') }}"></div>
        </div>
        <div class="row" style="margin-top:10px">
          <div class="col" style="flex:1 1 100%"><label>Summary</label><textarea name="summary">{{ pd.get('summary','') }}</textarea></div>
        </div>

        <div class="settings-row" style="margin-top:12px">
          <div>
            <div class="mini">Columns</div>
            <label class="inline"><input type="radio" name="columns" value="1" {% if settings.columns==1 %}checked{% endif %}> 1 Column</label>
            <label class="inline"><input type="radio" name="columns" value="2" {% if settings.columns==2 %}checked{% endif %}> 2 Columns</label>
          </div>
          <div>
            <div class="mini">Section separator</div>
            <label class="inline"><input type="checkbox" name="separator" value="1" {% if settings.separator %}checked{% endif %}> Show horizontal separators</label>
          </div>
          <div style="margin-left:auto">
            <button type="submit" formaction="{{ url_for('save_personal') }}">Save Personal</button>
            <button type="submit" formaction="{{ url_for('save_settings') }}">Save Settings</button>
          </div>
        </div>

      </form>
    </div>

    <div class="card">
      <div class="top-actions">
        <!-- Create category -->
        <form method="post" action="{{ url_for('create_category_route') }}">
          <input name="category_name" placeholder="Create new category (e.g. PROJECTS)" />
          <button type="submit">Create category</button>
        </form>

        <form method="get" action="{{ url_for('index') }}">
          <select name="category" onchange="this.form.submit()">
            <option value="">-- Select category --</option>
            {% for c in categories %}
              <option value="{{ c }}" {% if c==selected_category %}selected{% endif %}>{{ c }}</option>
            {% endfor %}
          </select>
        </form>

        <form method="get" action="{{ url_for('download_pdf') }}" style="margin-left:auto">
          <button type="submit" class="secondary">Download PDF</button>
        </form>
      </div>

      {% if selected_category %}
        <div style="margin-top:10px">
          <h3>Category: {{ selected_category }}</h3>

          <!-- Add entry -->
          <form method="post" action="{{ url_for('add_entry_route') }}">
            <input type="hidden" name="category" value="{{ selected_category }}" />
            <input name="entry_name" placeholder="Entry name (required)" />
            <input name="entry_link" placeholder="Optional link (https://...)" />
            <input name="entry_date" type="date" placeholder="Optional date" />
            <button type="submit">Add Entry</button>
          </form>

          <div style="margin-top:8px">
            <form method="post" action="{{ url_for('delete_category_route') }}">
              <input type="hidden" name="category" value="{{ selected_category }}" />
              <button type="submit" class="danger">Delete category</button>
            </form>
          </div>

          <div class="grid" style="margin-top:10px">
            <div class="card" style="box-shadow:none; border:1px solid rgba(255,255,255,0.03)">
              <h4>Entries</h4>
              {% if entries %}
                {% for e in entries %}
                  <div class="item">
                    <b>{{ e.name }}</b> — {{ e.date|fmtdate }}
                    {% if e.link %} — <a href="{{ e.link }}" target="_blank">link</a>{% endif %}
                    <form method="post" action="{{ url_for('delete_entry_route') }}" style="display:inline-block;margin-left:8px">
                      <input type="hidden" name="category" value="{{ selected_category }}" />
                      <input type="hidden" name="index" value="{{ loop.index0 }}" />
                      <button type="submit" style="background:#ff8b8b;padding:4px 8px;border-radius:6px">Delete</button>
                    </form>
                  </div>
                {% endfor %}
              {% else %}
                <div class="muted">No entries yet in this category.</div>
              {% endif %}
            </div>
          </div>
        </div>
      {% else %}
        <div class="muted" style="margin-top:10px">Select a category to view or add entries.</div>
      {% endif %}
    </div>

    <div class="card">
      <h3>Live Resume Preview (A4)</h3>
      <div class="preview-wrap">
        <div class="a4">
          <h2>{{ pd.get('name','Your Name') }}</h2>
          <div class="sub">
            {{ pd.get('email','') }}
            {% if pd.get('phone') %} | {{ pd.get('phone') }}{% endif %}
            {% if pd.get('address') %} | {{ pd.get('address') }}{% endif %}
            {% if pd.get('dob') %} | DOB: {{ pd.get('dob')|fmtdate }}{% endif %}
          </div>

          {% if pd.get('summary') %}
            <div class="section {% if settings.separator %}separator{% endif %}">
              <h4>Summary</h4>
              <div class="item">{{ pd.get('summary') }}</div>
            </div>
          {% endif %}

          <div class="columns count-{{ settings.columns }}">
            {% for cat, items in all_categories.items() %}
              <div class="section {% if settings.separator %}separator{% endif %}">
                <h4>{{ cat }}</h4>
                {% if items %}
                  {% for e in items %}
                    <div class="item">
                      <b>{{ e.name }}</b> — {{ e.date|fmtdate }}
                      {% if e.link %} — <a href="{{ e.link }}" target="_blank">link</a>{% endif %}
                    </div>
                  {% endfor %}
                {% else %}
                  <div class="item muted">No items yet.</div>
                {% endif %}
              </div>
            {% endfor %}
          </div>
        </div>
      </div>
      <div class="muted" style="margin-top:6px">Tip: The preview above is sized to A4 and will flow content into columns automatically based on settings.</div>
    </div>
  </div>
</body>
</html>
    """

    def flashes_for_template():
        raw = get_flashed_messages(with_categories=True)
        return [(message, category) for category, message in raw]

    @app.route("/", methods=["GET"])
    def index():
        try:
            data = load_data()
            cats = list(data.get("categories", {}).keys())
            selected = request.args.get("category") or (cats[0] if cats else "")
            entries = data.get("categories", {}).get(selected, []) if selected else []
            settings = data.get("settings", default_structure()["settings"])
            return render_template_string(
                TEMPLATE,
                save_path=str(SAVE_PATH),
                pd=data.get("personal_details", {}),
                categories=cats,
                selected_category=selected,
                entries=entries,
                all_categories=data.get("categories", {}),
                flashes=flashes_for_template(),
                today=datetime.date.today().isoformat(),
                settings=settings
            )
        except Exception as e:
            logging.exception("Unhandled error in index")
            return f"An error occurred: {e}\n\n{traceback.format_exc()}", 500

    @app.route("/save_personal", methods=["POST"])
    def save_personal():
        try:
            details = {
                "name": request.form.get("name", ""),
                "email": request.form.get("email", ""),
                "phone": request.form.get("phone", ""),
                "address": request.form.get("address", ""),
                "dob": request.form.get("dob", ""),
                "summary": request.form.get("summary", ""),
            }
            set_personal_details(details)
            # Also consider saving settings from form if present
            settings_payload = {}
            if request.form.get("columns"):
                settings_payload["columns"] = int(request.form.get("columns"))
            if request.form.get("separator") is not None:
                settings_payload["separator"] = True
            else:
                # If checkbox absent, treat as false
                if "columns" in request.form:
                    settings_payload["separator"] = False
            if settings_payload:
                set_settings(settings_payload)
            flash("Personal details saved.", "success")
        except Exception:
            logging.exception("save_personal failed")
            flash("Internal error while saving personal details.", "error")
        return redirect(url_for("index"))

    @app.route("/save_settings", methods=["POST"])
    def save_settings():
        try:
            cols = request.form.get("columns")
            sep = request.form.get("separator")
            payload = {}
            if cols:
                try:
                    payload["columns"] = int(cols)
                except Exception:
                    payload["columns"] = 2
            payload["separator"] = bool(sep)
            set_settings(payload)
            flash("Settings saved.", "success")
        except Exception:
            logging.exception("save_settings failed")
            flash("Internal error while saving settings.", "error")
        return redirect(url_for("index"))

    @app.route("/create_category", methods=["POST"])
    def create_category_route():
        try:
            ok = add_category(request.form.get("category_name", ""))
            if ok:
                flash("Category created.", "success")
            else:
                flash("Category name is empty or already exists.", "error")
        except Exception:
            logging.exception("create_category failed")
            flash("Internal error while creating category.", "error")
        return redirect(url_for("index"))

    @app.route("/add_entry", methods=["POST"])
    def add_entry_route():
        try:
            cat = request.form.get("category", "")
            name = request.form.get("entry_name", "")
            link = request.form.get("entry_link", "")
            date = request.form.get("entry_date", "")  # optional; backend defaults
            ok = add_entry(cat, name, link, date)
            if ok:
                flash("Entry added.", "success")
            else:
                flash("Failed to add entry. Ensure a category is selected and name is provided.", "error")
        except Exception:
            logging.exception("add_entry failed")
            flash("Internal error while adding entry.", "error")
        return redirect(url_for("index", category=request.form.get("category", "")))

    @app.route("/delete_category", methods=["POST"])
    def delete_category_route():
        try:
            ok = delete_category(request.form.get("category", ""))
            if ok:
                flash("Category deleted.", "success")
            else:
                flash("Could not delete category.", "error")
        except Exception:
            logging.exception("delete_category failed")
            flash("Internal error while deleting category.", "error")
        return redirect(url_for("index"))

    @app.route("/delete_entry", methods=["POST"])
    def delete_entry_route():
        try:
            cat = request.form.get("category", "")
            idx_raw = request.form.get("index", "")
            idx = int(idx_raw) if str(idx_raw).isdigit() else -1
            ok = delete_entry(cat, idx)
            if ok:
                flash("Entry deleted.", "success")
            else:
                flash("Could not delete entry.", "error")
        except Exception:
            logging.exception("delete_entry failed")
            flash("Internal error while deleting entry.", "error")
        return redirect(url_for("index", category=request.form.get("category", "")))

    @app.route("/download_pdf", methods=["GET"])
    def download_pdf():
        try:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            path = generate_pdf(PDF_PATH)
            if path is None or not path.exists():
                flash("PDF export requires 'reportlab'. Install with: pip install reportlab", "error")
                return redirect(url_for("index"))
            return send_file(str(path), as_attachment=True, download_name="resume.pdf")
        except Exception:
            logging.exception("download_pdf failed")
            flash("Internal error while generating PDF.", "error")
            return redirect(url_for("index"))

    logging.info("Starting web UI on http://127.0.0.1:5000")
    app.run(debug=False, port=5000)

# ---------------------------- Entrypoint ---------------------------
def main():
    try:
        import flask  # check availability
        run_flask()
    except Exception:
        logging.info("Flask not available / error importing; please install Flask:\n  pip install flask")
        raise

if __name__ == "__main__":
    main()
