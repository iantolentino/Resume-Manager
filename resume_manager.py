#!/usr/bin/env python3
"""
Resume / Details Manager — A4 Canvas + Two-Column Preview + Two-Column PDF
- Personal details (with DOB + dates tracked)
- Categories with entries (name, optional link, date). Dates auto-default to today if blank.
- Safe JSON with atomic writes and local lock
- HTML live preview sized like A4 "PDF canvas" in two columns (balanced with CSS multi-columns)
- Two-column PDF export using reportlab (graceful message if reportlab not installed)

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
SAVE_PATH = Path("C:/ResumeDetails/resume_data.json")
SAVE_DIR = SAVE_PATH.parent
PDF_PATH = SAVE_DIR / "resume.pdf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
file_lock = threading.Lock()

# ----------------------- Storage Utilities ------------------------
def ensure_folder():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

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
                base = {"personal_details": {}, "categories": {}}
                atomic_save(base)
                return base
            with file_lock, open(SAVE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (PermissionError, OSError, json.JSONDecodeError) as e:
            logging.warning("load_data attempt %d failed: %s", attempt + 1, e)
            if isinstance(e, json.JSONDecodeError):
                try:
                    backup = SAVE_DIR / f"corrupt_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    shutil.copy2(SAVE_PATH, backup)
                    logging.info("Backed up corrupt JSON to %s", backup)
                except Exception:
                    logging.exception("Failed to backup corrupt JSON")
                base = {"personal_details": {}, "categories": {}}
                atomic_save(base)
                return base
            time.sleep(retry_delay)
    logging.error("load_data failed after retries; returning empty structure.")
    return {"personal_details": {}, "categories": {}}

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

# -------------------------- PDF Export ---------------------------
def generate_pdf(output_path: Path) -> Optional[Path]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except Exception as e:
        logging.warning("reportlab not installed: %s", e)
        return None

    data = load_data()
    pd = data.get("personal_details", {})
    cats = data.get("categories", {})

    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    H1 = styles["Heading1"]; H1.spaceAfter = 6
    H2 = styles["Heading2"]; H2.spaceBefore = 6; H2.spaceAfter = 4
    N = styles["BodyText"]; N.spaceAfter = 2

    doc = BaseDocTemplate(str(output_path), pagesize=A4,
                          leftMargin=14*mm, rightMargin=14*mm,
                          topMargin=14*mm, bottomMargin=14*mm)

    frame_gap = 8*mm
    page_w, page_h = A4
    usable_w = page_w - doc.leftMargin - doc.rightMargin
    col_w = (usable_w - frame_gap) / 2
    frame_h = page_h - doc.topMargin - doc.bottomMargin
    x0 = doc.leftMargin
    y0 = doc.bottomMargin

    frames = [
        Frame(x0, y0, col_w, frame_h, id='col1', showBoundary=0),
        Frame(x0 + col_w + frame_gap, y0, col_w, frame_h, id='col2', showBoundary=0),
    ]
    doc.addPageTemplates(PageTemplate(id='TwoCol', frames=frames))

    story: List[Any] = []

    # Header
    name = pd.get("name") or "Your Name"
    header_parts = [Paragraph(name, H1)]
    contact_line = " | ".join(filter(None, [
        pd.get("email", ""),
        pd.get("phone", ""),
        pd.get("address", ""),
        f"DOB: {format_date(pd.get('dob', ''))}" if pd.get("dob") else ""
    ]))
    if contact_line:
        header_parts.append(Paragraph(contact_line, N))
    if pd.get("summary"):
        header_parts.append(Paragraph(pd["summary"], N))
    header_parts.append(Spacer(1, 6))
    story.append(KeepTogether(header_parts))

    # Categories
    for cat, items in cats.items():
        story.append(Paragraph(cat, H2))
        for e in items:
            line = f"<b>{escape_html(e.get('name',''))}</b>"
            if e.get("date"):
                line += f" — {escape_html(format_date(e['date']))}"
            if e.get("link"):
                line += f" — <font color='{colors.HexColor('#1a73e8')}'>{escape_html(e['link'])}</font>"
            story.append(Paragraph(line, N))
        story.append(Spacer(1, 6))

    doc.build(story)
    return output_path

# --------------------------- Utils --------------------------------
def escape_html(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

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
  <style>
    :root{
      --bg:#f6f8fb; --card:#fff; --muted:#667085; --ink:#1f2937; --accent:#2563eb; --danger:#e11d48;
      --a4w:210mm; --a4h:297mm;
    }
    *{box-sizing:border-box}
    body{font-family:system-ui,Segoe UI,Roboto,Arial; margin:0; padding:24px; background:var(--bg); color:var(--ink)}
    .container{max-width:1100px; margin:0 auto}
    .card{background:var(--card); padding:18px; border-radius:12px; box-shadow:0 6px 18px rgba(16,24,40,.06); margin-bottom:18px}
    h1{margin:0 0 12px}
    h3{margin:12px 0 8px}
    input[type=text], input[type=date], textarea, select{width:100%; padding:8px 10px; border:1px solid #e5e7eb; border-radius:8px}
    textarea{min-height:80px}
    button{background:var(--accent); color:#fff; border:none; padding:8px 12px; border-radius:8px; cursor:pointer}
    button.secondary{background:#475569}
    button.danger{background:var(--danger)}
    .row{display:flex; gap:12px; flex-wrap:wrap}
    .col{flex:1 1 280px}
    .muted{color:var(--muted); font-size:13px}
    .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px}
    .flash{padding:10px;border-radius:8px;margin:8px 0}
    .flash.success{background:#ecfdf3;color:#054f31}
    .flash.error{background:#fef3f2;color:#7a271a}

    .preview-wrap{overflow:auto; max-height:75vh; padding:6px; border:1px dashed #e5e7eb; border-radius:12px; background:#fafafa}
    .a4{
      width: var(--a4w); min-height: var(--a4h);
      background:#fff; color:#111827;
      margin:0 auto; padding:18mm 16mm;
      box-shadow:0 3px 12px rgba(0,0,0,.08); border-radius:6px;
    }
    .a4 h2{margin:0 0 4mm}
    .a4 .sub{color:#374151; font-size:11pt; margin-bottom:6mm}
    .columns{ column-count:2; column-gap:12mm; }
    .section{break-inside:avoid; margin:0 0 6mm}
    .section h4{margin:0 0 2mm; border-bottom:1px solid #e5e7eb; padding-bottom:2mm}
    .item{margin:1mm 0; font-size:11pt}
    .item a{color:#1d4ed8; text-decoration:none}
    .top-actions{display:flex; gap:8px; align-items:center; flex-wrap:wrap}
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
        <div class="row">
          <div class="col"><label>Address</label><input type="text" name="address" value="{{ pd.get('address','') }}"></div>
          <div class="col"><label>Date of Birth</label><input type="date" name="dob" value="{{ pd.get('dob','') }}"></div>
        </div>
        <div class="row">
          <div class="col" style="flex:1 1 100%"><label>Summary</label><textarea name="summary">{{ pd.get('summary','') }}</textarea></div>
        </div>
        <button type="submit">Save Personal Details</button>
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
            <!-- date is optional; backend defaults to today -->
            <button type="submit">Add Entry</button>
          </form>

          <div style="margin-top:8px">
            <form method="post" action="{{ url_for('delete_category_route') }}">
              <input type="hidden" name="category" value="{{ selected_category }}" />
              <button type="submit" style="background:#ff6b6b">Delete category</button>
            </form>
          </div>

          <div class="grid" style="margin-top:10px">
            <div class="card" style="box-shadow:none; border:1px solid #eef2f7">
              <h4>Entries</h4>
              {% if entries %}
                {% for e in entries %}
                  <div class="item">
                    <b>{{ e.name }}</b> — {{ e.date|fmtdate }}
                    {% if e.link %} — <a href="{{ e.link }}" target="_blank">link</a>{% endif %}
                    <form method="post" action="{{ url_for('delete_entry_route') }}">
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
      <h3>Live Resume Preview</h3>
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
            <div class="section">
              <h4>Summary</h4>
              <div class="item">{{ pd.get('summary') }}</div>
            </div>
          {% endif %}

          <div class="columns">
            {% for cat, items in all_categories.items() %}
              <div class="section">
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
      <div class="muted" style="margin-top:6px">Tip: The preview above is sized to A4 and flows content into two columns automatically.</div>
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
            return render_template_string(
                TEMPLATE,
                save_path=str(SAVE_PATH),
                pd=data.get("personal_details", {}),
                categories=cats,
                selected_category=selected,
                entries=entries,
                all_categories=data.get("categories", {}),
                flashes=flashes_for_template(),
                today=datetime.date.today().isoformat()
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
            flash("Personal details saved.", "success")
        except Exception:
            logging.exception("save_personal failed")
            flash("Internal error while saving personal details.", "error")
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
            date = request.form.get("entry_date", "")  # optional; form doesn't send it; backend defaults
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
        import flask  # just to check availability
        run_flask()
    except Exception:
        logging.info("Flask not available / error importing; please install Flask:\n  pip install flask")
        raise

if __name__ == "__main__":
    main()
