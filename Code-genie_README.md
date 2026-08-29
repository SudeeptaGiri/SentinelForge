# Person 4: Code Generation & QA Self-Healing Implementation

## 🎯 Overview

This implementation demonstrates autonomous code generation and self-healing test execution using **Google ADK agents with Gemini AI**.

### Key Features

✅ **LLM-Powered Code Generation** - Gemini intelligently generates code based on migration plans  
✅ **No Hardcoded Fixes** - All healing is dynamic using AI reasoning  
✅ **Self-Healing Test Loop** - Automatically detects and fixes test failures  
✅ **Git Integration** - Proper version control with branches and commits  
✅ **Graceful Degradation** - Works with template fallbacks if Gemini is unavailable  
✅ **Bounded Retries** - Max 3 healing attempts to prevent infinite loops  

---

## 📂 Structure

```
demo_app/                      # Test Flask application
├── app.py                     # Flask app (initially missing /healthz)
├── tests/
│   ├── test_app.py           # Passing tests
│   └── test_healthz.py       # Failing tests (triggers self-healing)
└── requirements.txt

src/agents/
├── code_gen_agent.py         # CodeGeneratorAgent (Gemini-powered)
└── qa_agent.py               # QAAgent with self-healing (Gemini-powered)

src/mcp_servers/
└── server_git.py             # Git operations wrapper

test_person4_demo.py          # Main demo runner
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install SentinelForge dependencies
pip install -r requirements.txt

# OR if using poetry
poetry install

# Install demo app dependencies
cd demo_app
pip install -r requirements.txt
cd ..
```

### 2. Set Up Gemini API Key (Recommended)

For full AI-powered capabilities:

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your-api-key-here"

# Linux/Mac
export GEMINI_API_KEY="your-api-key-here"
```

**Without API key**: The agents will use template-based fallbacks (still functional but less intelligent).

### 3. Run the Demo

```bash
python test_person4_demo.py
```

Expected output:
```
🚀 SENTINELFORGE: CODE GENERATION & SELF-HEALING DEMO
======================================================================

📋 Step 1: Create Migration Plan
  Target Platform: CloudRun
  Monthly Savings: $434.0 (70.9%)

🔧 Step 2: Generate Code Changes
  ✅ Generated changes on branch: feature/cloud-run-migration
  📝 Files changed: app.py, Dockerfile

🧪 Step 3: Run Tests with Self-Healing
  Test Run #1: ❌ FAILED (missing /healthz endpoint)
  🔧 Self-healing in progress...
  Test Run #2: ✅ ALL TESTS PASSED!

📊 FINAL RESULTS
  Total test runs: 2
  Healing fixes applied: 1
  ✅ ✅ ✅  ALL TESTS PASSED! ✅ ✅ ✅

🎉 DEMO COMPLETE!
```

---

## 🧪 Testing

### Run Unit Tests

```bash
# Test the agents in isolation
pytest tests/unit/test_code_gen_agent.py -v
pytest tests/unit/test_qa_agent.py -v
```

### Test Demo App Directly

```bash
cd demo_app

# Run tests (should fail initially)
pytest tests/ -v

# After code generation + healing, tests should pass
pytest tests/ -v
```

---

## 🏗️ Architecture

### CodeGeneratorAgent

**Purpose**: Generate code changes based on approved migration plans

**Flow**:
1. Receive `MigrationPlan` from Cost Agent
2. Create git feature branch
3. Use Gemini to generate:
   - Health check endpoints (`/healthz`)
   - Dockerfiles
   - Service configurations
4. Commit changes with descriptive messages
5. Return `CodeDiff` object for Gate 2 review

**Key Methods**:
- `generate_code_changes()` - Main entry point
- `_add_healthz_endpoint()` - Gemini-powered endpoint generation
- `_generate_dockerfile()` - Gemini-powered Dockerfile creation

---

### QAAgent

**Purpose**: Run tests and automatically heal failures using AI

**Flow**:
1. Execute pytest test suite
2. If tests fail:
   - Extract error context from output
   - Ask Gemini to analyze and generate fix
   - Apply fix to codebase
   - Commit fix with git
   - Re-run tests
3. Repeat up to 3 times (configurable)
4. Report success/failure with healing history

**Key Methods**:
- `run_tests_with_self_heal()` - Main orchestration
- `_execute_tests()` - Run pytest and capture output
- `_analyze_and_heal()` - Gemini-powered healing
- `_generate_fix_with_gemini()` - AI fix generation
- `_apply_fix()` - Write and commit fix

---

## 🎯 Demo Scenario

1. **Initial State**: Flask app missing `/healthz` endpoint
2. **Code Gen**: Agent adds health check (intentionally incomplete for demo)
3. **Test Run #1**: Tests fail - 404 on `/healthz`
4. **Self-Healing**: 
   - QA agent detects missing route handler
   - Gemini generates complete fix
   - Fix is applied and committed
5. **Test Run #2**: All tests pass ✅
6. **Result**: Automated code → test → fix → verify cycle

---

## ⚙️ Configuration

Configuration is loaded from `config/agent_config.yaml`:

```yaml
agents:
  code_gen_agent:
    model: gemini-2.5-pro
    max_retries: 3
  qa_agent:
    model: gemini-2.5-pro
    max_retries: 3
```

---

## 🔍 Key Design Decisions

### 1. **ADK Agent Pattern**
Following proper ADK patterns with Gemini client integration matching the existing `GeminiClient` in `orchestrator/gemini_client.py`.

### 2. **No Hardcoded Fixes**
All fixes are generated dynamically by Gemini based on:
- Error context
- Current code state
- Testing best practices

### 3. **Graceful Degradation**
If Gemini API is unavailable:
- Falls back to pattern-based detection
- Uses template-based code generation
- Still functional for basic demo scenarios

### 4. **Git-First Workflow**
Every change is tracked in git:
- Feature branches for code generation
- Individual commits for each healing attempt
- Full audit trail of all changes

### 5. **Bounded Retry Logic**
Maximum 3 healing attempts to prevent:
- Infinite loops
- Cost explosion
- Unpredictable behavior

---

## 🐛 Troubleshooting

### Issue: "Not a git repository"
**Solution**: Ensure `demo_app/.git` exists. Re-run:
```bash
cd demo_app
git init
cd ..
```

### Issue: "Gemini SDK unavailable"
**Solution**: Install the SDK:
```bash
pip install google-genai
```

### Issue: Tests always pass/never fail
**Solution**: The demo app intentionally has missing `/healthz` endpoint. Ensure you're using the original `app.py` without the endpoint.

### Issue: "pytest not found"
**Solution**: Install pytest:
```bash
cd demo_app
pip install -r requirements.txt
```

---

## 🚀 Next Steps / Future Enhancements

1. **Multi-Strategy Healing** - Generate and rank multiple fix options
2. **Root Cause Analysis** - Identify underlying issues, not just symptoms
3. **Test Coverage Analysis** - Auto-generate missing tests
4. **Security Scanning** - Scan generated code for vulnerabilities
5. **Performance Testing** - Add load testing to the QA loop
6. **Cross-Project Learning** - Learn from healing patterns across projects

---

## 📊 Success Metrics

For the hackathon demo, this implementation achieves:

✅ **Autonomous Operation** - Zero manual intervention from code gen to healed tests  
✅ **Reproducibility** - 100% consistent demo results  
✅ **Visibility** - Clear logging of each step for demo narration  
✅ **Integration** - Clean `CodeDiff` output for Person 1's orchestrator  
✅ **Best Practices** - Proper ADK patterns, git workflow, error handling  

---

## 👤 Author

**Person 4** - Code Generation & QA/Self-Healing Agent Lead

Part of the SentinelForge autonomous DevSecOps agent system.

