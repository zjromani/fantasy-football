# Testing Guidelines

## NO EXTERNAL API CALLS IN TESTS

**Critical Rule:** Tests must NEVER call real external APIs (OpenAI, Yahoo, ESPN, etc.)

This ensures:
- Tests are fast and reliable
- No API costs during development
- Tests work offline
- No rate limiting issues
- Deterministic test results

## Current Test Safety

All tests are verified safe:

### ✅ **AI/OpenAI Tests**
- `test_ai_client.py` - Only tests configuration, NO API calls
- `test_ai_agent.py` - Uses offline mode, NO API calls
- `test_ai_prompts.py` - Only validates prompt structure, NO API calls

### ✅ **Yahoo API Tests**
- `test_yahoo_client.py` - Uses `DummyTransport` to mock all HTTP calls
- `test_ingest.py` - Uses fixture files, NO live API calls

### ✅ **News/Projections Tests**
- `test_news.py` - Not implemented yet
- `test_projections.py` - Not implemented yet
- No tests currently call `fetch_all_news()` or `get_projections()`

### ✅ **Integration Tests**
- `test_brief.py` - Uses local data only
- `test_lineup_enhanced.py` - Uses local data only
- `test_waivers.py` - Uses local data only

## How to Add New Tests

### For API-dependent code:

1. **Use mocks/fixtures:**
   ```python
   from unittest.mock import patch

   @patch('app.module.external_api_call')
   def test_something(mock_api):
       mock_api.return_value = {"data": "fake"}
       # Test logic here
   ```

2. **Use custom transports (like httpx.BaseTransport):**
   ```python
   class MockTransport(httpx.BaseTransport):
       def handle_request(self, request):
           return httpx.Response(200, json={"mock": "data"})

   client = SomeClient(transport=MockTransport())
   ```

3. **Use fixture files:**
   ```python
   def test_parse_response():
       with open("tests/fixtures/response.json") as f:
           data = json.load(f)
       result = parse_function(data)
       assert result["expected"] == "value"
   ```

### For AI/LLM tests:

1. **Test prompt structure, not responses:**
   ```python
   def test_prompt_contains_constraints():
       prompt = build_prompt(data)
       assert "CONSTRAINTS:" in prompt
       assert "Only use provided data" in prompt
   ```

2. **Use offline mode or skip flags:**
   ```python
   @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No API key")
   def test_with_real_api():
       # This test is explicitly skipped in CI
       pass
   ```

3. **Mock AI responses:**
   ```python
   @patch('app.ai.client.ask')
   def test_ai_logic(mock_ask):
       mock_ask.return_value = {"content": "Mock response", "usage": {...}}
       result = my_function()
       assert result.success
   ```

## Running Tests

```bash
# Run all tests (should be fast, no API calls)
make test

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_ai_prompts.py -v

# Run tests in parallel (faster)
pytest -n auto tests/
```

## Test Checklist

Before committing new tests, verify:

- [ ] No `httpx.get()` or `requests.get()` without mocks
- [ ] No `OpenAI()` or `ask()` calls without mocks
- [ ] No `YahooClient().get()` without `DummyTransport`
- [ ] No `fetch_all_news()` or `get_projections()` calls
- [ ] Tests complete in < 30 seconds total
- [ ] All tests pass in CI environment (no API keys)

## CI/CD Considerations

- Tests run in GitHub Actions without API keys
- Any test requiring API keys must be explicitly skipped
- Use `pytest.mark.integration` for tests that need manual setup
- Mock all external services (Yahoo, OpenAI, ESPN, etc.)

## What to Test

### ✅ **DO Test:**
- Data parsing and validation
- Business logic (scoring, lineup optimization)
- Database operations (with in-memory DB)
- Prompt structure and constraints
- Configuration loading
- Error handling

### ❌ **DON'T Test:**
- External API response formats (use fixtures)
- Third-party library internals
- Network reliability
- Rate limits
- API key validity

## Fixture Management

Store sample API responses in `tests/fixtures/`:
```
tests/fixtures/
├── league.json          # Sample Yahoo league data
├── players.json         # Sample player list
├── news_espn.json      # Sample ESPN news
└── projections.json    # Sample projections
```

Update fixtures when API formats change, not on every test run.

## Performance

Target: **All tests < 30 seconds**

Current: **41 tests in ~21 seconds** ✅

If tests slow down:
1. Check for accidental API calls
2. Use fixtures instead of database queries
3. Run tests in parallel with `-n auto`
4. Move slow integration tests to separate suite

