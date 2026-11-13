from agent.anthropic_adapter import _convert_content_part_to_anthropic


def test_video_url_is_converted_to_minimax_video_block():
    result = _convert_content_part_to_anthropic(
        {"type": "video_url", "video_url": {"url": "https://example.test/clip.mp4"}}
    )

    assert result == {
        "type": "video",
        "source": {"type": "url", "url": "https://example.test/clip.mp4"},
    }


def test_video_data_url_preserves_media_type_and_payload():
    result = _convert_content_part_to_anthropic(
        {"type": "video_url", "video_url": {"url": "data:video/webm;base64,AAAA"}}
    )

    assert result == {
        "type": "video",
        "source": {"type": "base64", "media_type": "video/webm", "data": "AAAA"},
    }
