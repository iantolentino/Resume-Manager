#!/usr/bin/env python3
"""
Resume / Details Manager — Fixed & robust version
- Saves data to C:/ResumeDetails/8_19_25_info.json (creates folder if needed)
- Supports categories, selecting categories, adding entries (name + optional link)
- Uses Windows-safe atomic writes and a lock to avoid PermissionError / races
- Simple Flask web UI (if flask installed) or CLI fallback
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
import sys
import traceback

# Config
SAVE_PATH = Path("C:/ResumeDetails/8_19_25_info.json")
SAVE_DIR = SAVE_PATH.parent

# Logging config (prints to console)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# A lock to serialize read/write operations in this process (prevents races)
file_lock = threading.Lock()

def ensure_folder():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

def atomic_save(data: dict, max_attempts: int = 8, retry_delay: float = 0.12):
    """
    Windows-friendly atomic save:
      - write to a NamedTemporaryFile inside same dir (close it)
      - os.replace(temp, dest) with retry on PermissionError
      - wraps in file_lock to avoid concurrent access in-process
    """
    ensure_folder()
    temp_file = None
    with file_lock:
        try:
            # Create temp file inside same folder
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=str(SAVE_DIR), prefix="tmp_resume_", suffix=".json"
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
                    # atomic replace
                    os.replace(str(temp_file), str(SAVE_PATH))
                    logging.debug("Saved JSON to %s", SAVE_PATH)
                    break
                except PermissionError as e:
                    attempts += 1
                    logging.warning("PermissionError on replace attempt %d: %s", attempts, e)
                    if attempts >= max_attempts:
                        raise
                    time.sleep(retry_delay)
        finally:
            # cleanup leftover temp
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

def load_data(retries: int = 6, retry_delay: float = 0.08) -> dict:
    """
    Load JSON data with retries on transient permission/read errors.
    Ensures the file exists and returns a dict with "categories".
    """
    ensure_folder()
    for attempt in range(retries):
        try:
            if not SAVE_PATH.exists():
                base = {"categories": {}}
                atomic_save(base)
                return base
            with file_lock:
                with open(SAVE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (PermissionError, OSError, json.JSONDecodeError) as e:
            logging.warning("load_data attempt %d failed: %s", attempt + 1, e)
            # If file corrupted or invalid JSON, back it up and start fresh
            if isinstance(e, json.JSONDecodeError):
                try:
                    backup = SAVE_DIR / f"corrupt_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    shutil.copy2(SAVE_PATH, backup)
                    logging.info("Backed up corrupt JSON to %s", backup)
                except Exception:
                    logging.exception("Failed to backup corrupt JSON")
                base = {"categories": {}}
                atomic_save(base)
                return base
            time.sleep(retry_delay)
    # Final fallback: return empty base structure (avoid crashing)
    logging.error("load_data failed after retries; returning empty structure.")
    return {"categories": {}}

def add_category(name: str) -> bool:
    data = load_data()
    c = data.setdefault("categories", {})
    key = name.strip()
    if not key:
        return False
    if key in c:
        return False
    c[key] = []
    atomic_save(data)
    return True

def delete_category(name: str) -> bool:
    data = load_data()
    c = data.get("categories", {})
    key = name.strip()
    if key in c:
        del c[key]
        atomic_save(data)
        return True
    return False

def add_entry(category: str, name: str, link: str | None = None) -> bool:
    data = load_data()
    c = data.setdefault("categories", {})
    key = category.strip()
    if key not in c:
        return False
    entry = {
        "name": name.strip(),
        "link": link.strip() if link else None,
        "created_at": datetime.datetime.now().isoformat()
    }
    c[key].append(entry)
    atomic_save(data)
    return True

def delete_entry(category: str, index: int) -> bool:
    data = load_data()
    c = data.get("categories", {})
    key = category.strip()
    if key not in c:
        return False
    try:
        del c[key][index]
    except Exception:
        return False
    atomic_save(data)
    return True

def list_categories():
    data = load_data()
    return list(data.get("categories", {}).keys())

def list_entries(category: str):
    data = load_data()
    return data.get("categories", {}).get(category.strip(), [])

# CLI UI (unchanged behavior)
def cli_menu():
    print("="*40)
    print("Resume Details Manager (CLI)")
    print(f"Data file: {SAVE_PATH}")
    print("="*40)
    while True:
        print("\nChoose an action:")
        print("1) List categories")
        print("2) Create category")
        print("3) Select category and list entries")
        print("4) Add entry to a category")
        print("5) Show raw JSON path")
        print("6) Delete category")
        print("7) Delete entry")
        print("0) Exit")
        choice = input("> ").strip()
        if choice == "1":
            cats = list_categories()
            if not cats:
                print("No categories yet.")
            else:
                for i, c in enumerate(cats, 1):
                    print(f"{i}. {c} ({len(list_entries(c))} items)")
        elif choice == "2":
            name = input("New category name: ").strip()
            if not name:
                print("Empty name. Cancel.")
                continue
            ok = add_category(name)
            print("Created." if ok else "Category already exists / invalid.")
        elif choice == "3":
            cats = list_categories()
            if not cats:
                print("No categories. Create one first.")
                continue
            for i, c in enumerate(cats, 1):
                print(f"{i}) {c}")
            sel = input("Select number or name: ").strip()
            try:
                idx = int(sel) - 1
                category = cats[idx]
            except Exception:
                category = sel
            entries = list_entries(category)
            if entries is None:
                print("Category not found.")
            elif not entries:
                print(f"No entries under '{category}'.")
            else:
                print(f"Entries for '{category}':")
                for i, e in enumerate(entries, 1):
                    link = e.get("link") or "-"
                    created = e.get("created_at", "-")
                    print(f"{i}. {e.get('name')}  | link: {link}  | added: {created}")
        elif choice == "4":
            cats = list_categories()
            if not cats:
                print("No categories. Create one first.")
                continue
            for i, c in enumerate(cats, 1):
                print(f"{i}) {c}")
            sel = input("Select category number or name to add to: ").strip()
            try:
                idx = int(sel) - 1
                category = cats[idx]
            except Exception:
                category = sel
            if category not in list_categories():
                print("Category not found.")
                continue
            name = input("Entry name (e.g. My Project): ").strip()
            link = input("Optional link (leave empty if none): ").strip()
            if not name:
                print("Entry must have a name.")
                continue
            ok = add_entry(category, name, link or None)
            print("Added." if ok else "Failed to add (category missing).")
        elif choice == "5":
            print(f"JSON saved at: {SAVE_PATH}")
        elif choice == "6":
            name = input("Category name to delete: ").strip()
            if not name:
                print("Cancelled.")
                continue
            ok = delete_category(name)
            print("Deleted." if ok else "Category not found.")
        elif choice == "7":
            cat = input("Category name: ").strip()
            entries = list_entries(cat)
            if not entries:
                print("No entries or category not found.")
                continue
            for i,e in enumerate(entries,1):
                print(f"{i}) {e.get('name')} (link:{e.get('link') or '-'})")
            idx = input("Index to delete (number): ").strip()
            try:
                i = int(idx)-1
                ok = delete_entry(cat,i)
                print("Deleted." if ok else "Failed to delete.")
            except Exception:
                print("Invalid index.")
        elif choice == "0":
            print("Bye.")
            break
        else:
            print("Unknown option.")

# Flask UI
def run_flask():
    try:
        from flask import Flask, render_template_string, request, redirect, url_for, flash, get_flashed_messages
    except Exception:
        logging.info("Flask not installed. Falling back to CLI. (Install Flask with: pip install flask)")
        cli_menu()
        return

    app = Flask(__name__)
    app.secret_key = "replace-this-with-a-random-secret-if-deploying"

    BASE_HTML = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>Resume Details Manager</title>
      <style>
        body{font-family:system-ui,Segoe UI,Roboto,Arial; margin:30px; background:#f7f9fc;}
        .card{background:white;padding:18px;border-radius:10px;box-shadow:0 6px 18px rgba(0,0,0,0.06);max-width:900px;margin:auto;}
        h1{font-size:20px;margin-bottom:6px}
        form{margin-top:12px}
        input[type=text], select{width:100%;padding:8px;margin:6px 0;border-radius:6px;border:1px solid #ddd;}
        button{background:#2b8cff;color:white;padding:8px 12px;border-radius:8px;border:none;cursor:pointer}
        .row{display:flex;gap:12px}
        .col{flex:1}
        .items{margin-top:12px}
        .item{padding:8px;border-bottom:1px solid #eee}
        .muted{color:#666;font-size:13px}
        .top-actions{display:flex;gap:8px;align-items:center}
        .flash{padding:8px;border-radius:6px;margin:8px 0}
        .flash.success{background:#e6ffed;color:#114b27}
        .flash.error{background:#ffe6e6;color:#5a1515}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Resume Details Manager</h1>
        <div class="muted">Data file: {{ save_path }}</div>

        {% for msg, cat in flashes %}
          <div class="flash {{ 'error' if cat=='error' else 'success' }}">{{ msg }}</div>
        {% endfor %}

        <hr/>
        <div class="top-actions">
          <form method="post" action="{{ url_for('create_category') }}" style="display:inline-block;flex:1">
            <input name="category_name" placeholder="Create new category (e.g. PROJECTS)" />
            <button type="submit">Create category</button>
          </form>

          <form method="get" action="{{ url_for('index') }}" style="display:inline-block">
            <select name="category" onchange="this.form.submit()">
              <option value="">-- Select category --</option>
              {% for c in categories %}
                <option value="{{ c }}" {% if c==selected_category %}selected{% endif %}>{{ c }}</option>
              {% endfor %}
            </select>
          </form>
        </div>

        <div style="margin-top:14px">
          {% if selected_category %}
            <h3>Category: {{ selected_category }}</h3>

            <form method="post" action="{{ url_for('add_entry_route') }}">
              <input type="hidden" name="category" value="{{ selected_category }}" />
              <input name="entry_name" placeholder="Entry name (required)" />
              <input name="entry_link" placeholder="Optional link (https://...)" />
              <button type="submit">Add Entry</button>
            </form>

            <div style="margin-top:8px">
              <form method="post" action="{{ url_for('delete_category_route') }}" onsubmit="return confirm('Delete this category and its entries?');">
                <input type="hidden" name="category" value="{{ selected_category }}" />
                <button type="submit" style="background:#ff6b6b">Delete category</button>
              </form>
            </div>

            <div class="items">
              {% if entries %}
                {% for e in entries %}
                  <div class="item">
                    <strong>{{ e.name }}</strong><br/>
                    <span class="muted">Link: {{ e.link or '-' }} | Added: {{ e.created_at }}</span>
                    <form method="post" action="{{ url_for('delete_entry_route') }}" style="display:inline-block;margin-left:12px">
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
          {% else %}
            <div class="muted">Select a category to view or add entries.</div>
          {% endif %}
        </div>
        <hr/>
        <div class="muted">JSON backup path: {{ save_path }}</div>
      </div>
    </body>
    </html>
    """

    def safe_action(fn, *args, **kwargs):
        """Run action and capture exceptions into flash and logs."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logging.exception("Exception in safe_action")
            return exc

    @app.route("/", methods=["GET"])
    def index():
        try:
            cats = list_categories()
            selected = request.args.get("category") or (cats[0] if cats else "")
            entries = list_entries(selected) if selected else []
            # get messages and convert to (message, category) for template
            raw = get_flashed_messages(with_categories=True)
            msgs = [(message, category) for category, message in raw]
            return render_template_string(BASE_HTML, categories=cats, selected_category=selected,
                                          entries=entries, save_path=str(SAVE_PATH), flashes=msgs)
        except Exception as e:
            logging.exception("Unhandled error in index route")
            # show a simple error to user
            return f"An error occurred: {e}\n\n{traceback.format_exc()}", 500

    @app.route("/create_category", methods=["POST"])
    def create_category():
        try:
            name = (request.form.get("category_name") or "").strip()
            if not name:
                flash("Category name empty.", "error")
            else:
                ok = add_category(name)
                if ok:
                    flash("Created.", "success")
                else:
                    flash("Category already exists or invalid.", "error")
        except Exception:
            logging.exception("create_category failed")
            flash("Internal error while creating category.", "error")
        return redirect(url_for("index"))

    @app.route("/add_entry", methods=["POST"])
    def add_entry_route():
        try:
            category = (request.form.get("category") or "").strip()
            name = (request.form.get("entry_name") or "").strip()
            link = (request.form.get("entry_link") or "").strip()
            if not category or not name:
                flash("Category and entry name are required.", "error")
                return redirect(url_for("index", category=category))
            ok = add_entry(category, name, link or None)
            flash("Added." if ok else "Category missing.", "success" if ok else "error")
        except Exception:
            logging.exception("add_entry_route failed")
            flash("Internal error while adding entry.", "error")
        return redirect(url_for("index", category=category))

    @app.route("/delete_category", methods=["POST"])
    def delete_category_route():
        try:
            category = (request.form.get("category") or "").strip()
            if not category:
                flash("No category provided.", "error")
            else:
                ok = delete_category(category)
                flash("Deleted." if ok else "Category not found.", "success" if ok else "error")
        except Exception:
            logging.exception("delete_category_route failed")
            flash("Internal error while deleting category.", "error")
        return redirect(url_for("index"))

    @app.route("/delete_entry", methods=["POST"])
    def delete_entry_route():
        try:
            category = (request.form.get("category") or "").strip()
            index = int(request.form.get("index", "-1"))
            if not category or index < 0:
                flash("Invalid parameters.", "error")
            else:
                ok = delete_entry(category, index)
                flash("Deleted." if ok else "Entry not found.", "success" if ok else "error")
        except Exception:
            logging.exception("delete_entry_route failed")
            flash("Internal error while deleting entry.", "error")
        return redirect(url_for("index", category=category))

    logging.info("Starting web UI on http://127.0.0.1:5000 (press CTRL+C to stop)")
    app.run(debug=False, port=5000)

# Entrypoint
def main():
    try:
        import flask  # type: ignore
        run_flask()
    except Exception:
        logging.info("Flask not available / error importing; running CLI.")
        cli_menu()

if __name__ == "__main__":
    main()
