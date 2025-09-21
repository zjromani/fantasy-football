from app.ai.tools import registry, invoke_tool


def test_post_inbox_tool():
    tools = registry()
    assert "post_inbox" in tools
    result = invoke_tool("post_inbox", {"title": "AI Test", "body": "hello"})
    assert "message_id" in result and isinstance(result["message_id"], int)


