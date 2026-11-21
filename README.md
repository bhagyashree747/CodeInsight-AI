# CodeInsight-AI

### AI-Powered Code Review and Self-Correcting Program Repair System

CodeInsight-AI is an intelligent code review and automated program repair system that uses Large Language Models (LLMs), Tree-sitter, and automated verification techniques to identify code issues, generate repair suggestions, and validate proposed fixes.

The system aims to make code reviews more efficient by combining AI-powered analysis with structured code understanding and project-level verification.

---

## 🚀 Project Overview

Traditional code review often requires developers to manually identify bugs, understand code context, suggest improvements, and verify whether proposed changes actually work.

CodeInsight-AI addresses this challenge through an integrated pipeline that:

1. Analyzes source code and identifies potential issues.
2. Uses code structure and contextual information to improve review quality.
3. Filters noisy or less relevant findings.
4. Generates AI-assisted repair suggestions.
5. Applies proposed patches in a controlled verification workflow.
6. Executes automated tests to evaluate whether the changes are valid.

The goal is not just to generate code fixes, but also to verify whether those fixes are reliable.

## ✨ Key Features

### 1. AI-Powered Code Review
- Analyzes source code using Large Language Models.
- Identifies potential bugs, code quality issues, and vulnerabilities.
- Generates structured review findings.
- Provides severity levels, confidence scores, descriptions, and suggested fixes.

### 2. Code Intelligence
- Uses Tree-sitter for syntax-aware code analysis.
- Extracts structural information from source code.
- Provides relevant code context for review and repair.
- Helps improve the relevance of AI-generated findings.

### 3. Intelligent Finding Filtering
- Filters noisy and less actionable findings.
- Helps prioritize meaningful issues.
- Reduces unnecessary review feedback.

### 4. AI-Based Code Repair
- Generates suggested code patches for identified issues.
- Supports automated repair workflows.
- Maintains repair information and verification results.

### 5. Automated Verification and Evaluation
- Validates generated patches using automated checks.
- Supports project-level verification.
- Executes selected pytest test cases.
- Supports custom Python interpreters.
- Supports isolated workspace execution.
- Tracks verification outcomes, including successful, failed, and retried repairs.

### 6. Interactive Dashboard
- React-based frontend dashboard.
- Displays code review findings and severity information.
- Shows AI-generated repair suggestions.
- Provides verification summaries.
- Integrates with the FastAPI backend.

---

## 🏗️ System Architecture

The project follows a modular pipeline architecture.

```text
             Source Code / Pull Request
                       |
                       v
                Code Analysis
                       |
                       v
             Tree-sitter Context
                       |
                       v
               AI Code Review
                       |
                       v
             Finding Classification
                       |
                       v
               Noise Filtering
                       |
                       v
               AI Patch Generation
                       |
                       v
             Patch Application
                       |
                       v
            Automated Verification
                       |
                       v
             Evaluation & Results
```

The frontend communicates with the FastAPI backend, which connects the user interface to the project's review and repair pipeline.

---

## 🛠️ Technology Stack

| Component | Technologies |
|---|---|
| Programming Language | Python |
| AI / LLM Integration | Large Language Models |
| Code Parsing | Tree-sitter |
| Backend | FastAPI |
| Frontend | React.js |
| Frontend Build Tool | Vite |
| Testing | Pytest |
| Data Visualization | Recharts |
| Version Control | Git and GitHub |

---

## 📁 Project Structure

```text
CodeInsight-AI/
│
├── app/
│   ├── verification/
│   │   ├── test_runner.py
│   │   ├── runner.py
│   │   └── repair_adapter.py
│   └── ...
│
├── api/
│   ├── __init__.py
│   └── main.py
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── assets/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
│
├── docs/
├── evaluation/
├── results/
├── tests/
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## ⚙️ Installation and Setup

### Prerequisites

Make sure the following are installed:

- Python
- Node.js and npm
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/bhagyashree747/CodeInsight-AI.git
cd CodeInsight-AI
```

### 2. Create a Python Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

On Linux/macOS:

```bash
source .venv/bin/activate
```

### 3. Install Backend Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the Environment

Create a local `.env` file in the project root.

For a mock/demo configuration:

```env
LLM_PROVIDER=mock
```

For an LLM provider integration, configure the appropriate provider settings and credentials according to the project's LLM client configuration.

**Important:** Never commit API keys, credentials, or your `.env` file to GitHub.

### 5. Start the Backend

From the project root:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Backend API:

`http://127.0.0.1:8000`

API health check:

`http://127.0.0.1:8000/api/health`

### 6. Start the Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the frontend using the local URL displayed by Vite, normally:

`http://localhost:5173`

---

## 🔌 API Endpoints

The FastAPI backend provides the following endpoints:

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Backend root endpoint |
| GET | `/api/health` | Checks backend health |
| POST | `/api/review` | Runs the code review pipeline |

### Example Review Request

```json
{
  "code": "def divide(a, b):\n    return a / b",
  "filename": "sample.py",
  "max_attempts": 2
}
```

Optional request fields include:

- `test_code`
- `extra_context`
- `context_level`

The review endpoint returns a structured response containing the pipeline result and success status.

---

## 🧪 Running Tests

The project uses Pytest for automated testing.

Run the complete test suite:

```bash
python -m pytest -q
```

Run verification-specific tests:

```bash
python -m pytest tests/
```

The verification module supports:

- Running selected pytest test cases.
- Custom Python interpreter selection.
- Separate workspace execution.
- Configurable test timeouts.

---

## 📊 Evaluation

CodeInsight-AI includes an evaluation component to assess the performance of the review and repair pipeline.

The evaluation workflow focuses on:

- Identifying meaningful code issues.
- Assessing actionable review findings.
- Evaluating generated patches.
- Verifying whether repairs pass automated checks.
- Tracking successful and failed verification attempts.

Evaluation resources and results are maintained in the `evaluation/` and `results/` directories.

---

## 🔮 Future Enhancements

Potential future improvements include:

- Expanded programming language support.
- Deeper GitHub Pull Request integration.
- Improved repair accuracy and patch validation.
- More comprehensive evaluation datasets.
- Advanced code context retrieval.
- Enhanced developer feedback and review workflows.

---

## 👥 Team Contributions

The project is developed collaboratively, with responsibilities divided across different modules:

| Member | Responsibility |
|---|---|
| Member 1 | AI-based repair and patch generation |
| Member 2 | Code intelligence and contextual analysis |
| Member 3 | Verification, automated testing, and evaluation |

The modules are integrated into a unified code review and repair workflow.

---

## 🎯 Project Objective

CodeInsight-AI aims to move beyond conventional AI-generated code suggestions by combining intelligent code analysis, automated repair, and systematic verification.

**Our goal is to build a more reliable, context-aware, and developer-friendly automated code review and repair system.**

---

## 📜 License

Add an appropriate open-source license before distributing the project publicly.

---

**Repository:** [CodeInsight-AI on GitHub](https://github.com/bhagyashree747/CodeInsight-AI)