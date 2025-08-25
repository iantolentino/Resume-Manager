# 📝 Resume Manager (Flask App)

A lightweight **Resume Manager Web App** built with Flask.  
It allows you to manage your resume interactively, including:

- Add **personal details** (name, email, phone).
- Create and delete **categories** (e.g., Skills, Projects, Education).
- Add, edit, and delete **entries** inside categories (with optional link & date).
- Manage **skills with proficiency levels**.
- Export your entire resume to a **PDF**.

---

## 🚀 Features

- **Personal Information**
  - Store and update your name, email, and phone number.

- **Categories**
  - Create categories like `Projects`, `Work Experience`, `Education`.
  - Delete categories when no longer needed.

- **Entries**
  - Add entries under a category (e.g., Project title, Job position).
  - Each entry can include a **name**, an optional **link**, and an optional **date**.
  - Delete entries individually.

- **Skills**
  - Add skills with a **proficiency level** (e.g., Python ★★★★☆).
  - Manage and remove skills easily.

- **Export to PDF**
  - Generate a clean PDF version of your resume.
  - Includes personal details, skills, and all categories/entries.

---

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/resume-manager.git
   cd resume-manager
   ```

2. **Create a virtual environment (recommended)**

   ```bash
   python -m venv venv
   source venv/bin/activate   # On Linux/Mac
   venv\Scripts\activate      # On Windows
   ```

3. **Install dependencies**

   ```bash
   pip install flask reportlab
   ```

---

## ▶️ Usage

1. **Run the Flask server**

   ```bash
   python resume_manager.py
   ```

2. **Open your browser** at:

   ```
   http://127.0.0.1:5000
   ```

3. **Start managing your resume**:

   * Add personal details.
   * Create categories.
   * Add entries to categories.
   * Add skills with proficiency levels.
   * Export everything to a PDF.

---

## 📂 Project Structure

```
resume-manager/
│
├── resume_manager.py   # Main Flask app
├── README.md           # Project documentation
└── requirements.txt    # Dependencies
```

---

## 📌 Example Categories

* **Education**

  * BSc in Computer Science (2018–2022)
* **Projects**

  * Resume Manager App (GitHub link)
* **Skills**

  * Python ★★★★☆
  * SQL ★★★☆☆
* **Work Experience**

  * Software Developer @ Company (2022–Present)

---

## 🖨️ Export Example

The generated PDF will look like:

```
John Doe
Email: john@example.com
Phone: +123456789

SKILLS
- Python ★★★★☆
- SQL ★★★☆☆

PROJECTS
- Resume Manager (https://github.com/johndoe/resume-manager) - 2025

WORK EXPERIENCE
- Software Developer @ Company - 2022–Present
```

---

## 📜 License

This project is open-source under the **MIT License**.

```

👉 Do you want me to also create a **`requirements.txt`** file (with exact dependencies like `flask` and `reportlab`) so setup is even easier?
```
