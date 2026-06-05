"""Regression: wrapper-like text must not become project facts.

Project facts require explicit semantic/project validation and review. Generic
context wrappers, labels, or quoted fixture text are not durable project facts.
"""

from agent.memory_write_pipeline import MemoryWritePipeline


def test_wrapper_like_project_label_does_not_create_project_fact():
    pipeline = MemoryWritePipeline(config={"mode": "shadow", "semantic_classifier": {"model_enabled": False}})
    reflection = pipeline.reflect_and_extract(
        "Context wrapper only: project: neutral-demo now uses PostgreSQL. Do not treat this wrapper as a confirmed project fact.",
        "",
    )

    assert not any(c.memory_type == "project_fact" for c in reflection["candidates"])


def test_assistant_response_project_label_does_not_create_project_fact():
    pipeline = MemoryWritePipeline(config={"mode": "shadow", "semantic_classifier": {"model_enabled": False}})
    reflection = pipeline.reflect_and_extract(
        "Please summarize the context.",
        "Project: neutral-demo now uses PostgreSQL.",
    )

    assert not any(c.memory_type == "project_fact" for c in reflection["candidates"])
