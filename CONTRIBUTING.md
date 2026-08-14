# Contributing to SpecLedger

Thank you for your interest in contributing to **SpecLedger**! We welcome contributions, bug reports, and feature suggestions from the open-source community.

---

## 🛠️ Development Setup

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/Yashasm18/specledger.git
   cd specledger
   ```

2. **Backend Setup (Python 3.11+):**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   ```

3. **Frontend Setup (React + Vite):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

## 🧪 Testing & Code Quality

Before submitting a pull request, ensure all tests and lint checks pass:

```bash
# Run pytest test suite (239 tests)
pytest tests/ -v

# Run Pylint code quality check (maintain rating >= 9.5/10)
pylint --rcfile=.pylintrc backend/
```

---

## 📋 Pull Request Process

1. Fork the repository and create a feature branch (`git checkout -b feature/your-feature-name`).
2. Adhere to Python PEP 8 standards, type hints, and Pylint configuration.
3. Add unit tests for any new normalization, parsing, or validation rules in `tests/`.
4. Ensure continuous integration checks pass on GitHub Actions.
5. Submit a pull request describing the changes and referencing any related issues.

---

## 📄 License
By contributing to SpecLedger, you agree that your contributions will be licensed under the [MIT License](LICENSE).
