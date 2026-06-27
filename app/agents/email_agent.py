"""This is an automatically generated file. Do not modify it.

This file was generated using `langgraph-gen` version 0.0.6.
To regenerate this file, run `langgraph-gen` with the source `yaml` file as an argument.

Usage:

1. Add the generated file to your project.
2. Create a new agent using the stub.

Below is a sample implementation of the generated stub:

```python
from typing_extensions import TypedDict

from email_agent import EmailAutomationOrchestrator

class SomeState(TypedDict):
    # define your attributes here
    foo: str

# Define stand-alone functions
def ingest_mailbox(state: SomeState) -> dict:
    print("In node: ingest_mailbox")
    return {
        # Add your state update logic here
    }


def enrich_messages(state: SomeState) -> dict:
    print("In node: enrich_messages")
    return {
        # Add your state update logic here
    }


def classify_intent(state: SomeState) -> dict:
    print("In node: classify_intent")
    return {
        # Add your state update logic here
    }


def urgent_escalation(state: SomeState) -> dict:
    print("In node: urgent_escalation")
    return {
        # Add your state update logic here
    }


def compliance_review(state: SomeState) -> dict:
    print("In node: compliance_review")
    return {
        # Add your state update logic here
    }


def sales_pipeline(state: SomeState) -> dict:
    print("In node: sales_pipeline")
    return {
        # Add your state update logic here
    }


def support_agent(state: SomeState) -> dict:
    print("In node: support_agent")
    return {
        # Add your state update logic here
    }


def zimbra_tools(state: SomeState) -> dict:
    print("In node: zimbra_tools")
    return {
        # Add your state update logic here
    }


def draft_support_reply(state: SomeState) -> dict:
    print("In node: draft_support_reply")
    return {
        # Add your state update logic here
    }


def newsletter_batch(state: SomeState) -> dict:
    print("In node: newsletter_batch")
    return {
        # Add your state update logic here
    }


def general_briefing(state: SomeState) -> dict:
    print("In node: general_briefing")
    return {
        # Add your state update logic here
    }


def merge_insights(state: SomeState) -> dict:
    print("In node: merge_insights")
    return {
        # Add your state update logic here
    }


def quality_review(state: SomeState) -> dict:
    print("In node: quality_review")
    return {
        # Add your state update logic here
    }


def refine_output(state: SomeState) -> dict:
    print("In node: refine_output")
    return {
        # Add your state update logic here
    }


def format_executive_report(state: SomeState) -> dict:
    print("In node: format_executive_report")
    return {
        # Add your state update logic here
    }


def route_intent(state: SomeState) -> str:
    print("In condition: route_intent")
    raise NotImplementedError("Implement me.")


def route_support_agent(state: SomeState) -> str:
    print("In condition: route_support_agent")
    raise NotImplementedError("Implement me.")


def route_quality(state: SomeState) -> str:
    print("In condition: route_quality")
    raise NotImplementedError("Implement me.")


agent = EmailAutomationOrchestrator(
    state_schema=SomeState,
    impl=[
        ("ingest_mailbox", ingest_mailbox),
        ("enrich_messages", enrich_messages),
        ("classify_intent", classify_intent),
        ("urgent_escalation", urgent_escalation),
        ("compliance_review", compliance_review),
        ("sales_pipeline", sales_pipeline),
        ("support_agent", support_agent),
        ("zimbra_tools", zimbra_tools),
        ("draft_support_reply", draft_support_reply),
        ("newsletter_batch", newsletter_batch),
        ("general_briefing", general_briefing),
        ("merge_insights", merge_insights),
        ("quality_review", quality_review),
        ("refine_output", refine_output),
        ("format_executive_report", format_executive_report),
        ("route_intent", route_intent),
        ("route_support_agent", route_support_agent),
        ("route_quality", route_quality),
    ]
)

compiled_agent = agent.compile()

print(compiled_agent.invoke({"foo": "bar"}))
"""

from typing import Callable, Any, Optional, Type

from langgraph.constants import START, END  # noqa: F401
from langgraph.graph import StateGraph


def EmailAutomationOrchestrator(
    *,
    state_schema: Optional[Type[Any]] = None,
    config_schema: Optional[Type[Any]] = None,
    input: Optional[Type[Any]] = None,
    output: Optional[Type[Any]] = None,
    impl: list[tuple[str, Callable]],
) -> StateGraph:
    """Create the state graph for EmailAutomationOrchestrator."""
    # Declare the state graph
    builder = StateGraph(
        state_schema, config_schema=config_schema, input=input, output=output
    )

    nodes_by_name = {name: imp for name, imp in impl}

    all_names = set(nodes_by_name)

    expected_implementations = {
        "ingest_mailbox",
        "enrich_messages",
        "classify_intent",
        "urgent_escalation",
        "compliance_review",
        "sales_pipeline",
        "support_agent",
        "zimbra_tools",
        "draft_support_reply",
        "newsletter_batch",
        "general_briefing",
        "merge_insights",
        "quality_review",
        "refine_output",
        "format_executive_report",
        "route_intent",
        "route_support_agent",
        "route_quality",
    }

    missing_nodes = expected_implementations - all_names
    if missing_nodes:
        raise ValueError(f"Missing implementations for: {missing_nodes}")

    extra_nodes = all_names - expected_implementations

    if extra_nodes:
        raise ValueError(
            f"Extra implementations for: {extra_nodes}. Please regenerate the stub."
        )

    # Add nodes
    builder.add_node("ingest_mailbox", nodes_by_name["ingest_mailbox"])
    builder.add_node("enrich_messages", nodes_by_name["enrich_messages"])
    builder.add_node("classify_intent", nodes_by_name["classify_intent"])
    builder.add_node("urgent_escalation", nodes_by_name["urgent_escalation"])
    builder.add_node("compliance_review", nodes_by_name["compliance_review"])
    builder.add_node("sales_pipeline", nodes_by_name["sales_pipeline"])
    builder.add_node("support_agent", nodes_by_name["support_agent"])
    builder.add_node("zimbra_tools", nodes_by_name["zimbra_tools"])
    builder.add_node("draft_support_reply", nodes_by_name["draft_support_reply"])
    builder.add_node("newsletter_batch", nodes_by_name["newsletter_batch"])
    builder.add_node("general_briefing", nodes_by_name["general_briefing"])
    builder.add_node("merge_insights", nodes_by_name["merge_insights"])
    builder.add_node("quality_review", nodes_by_name["quality_review"])
    builder.add_node("refine_output", nodes_by_name["refine_output"])
    builder.add_node("format_executive_report", nodes_by_name["format_executive_report"])

    # Add edges
    builder.add_edge(START, "ingest_mailbox")
    builder.add_edge("ingest_mailbox", "enrich_messages")
    builder.add_edge("enrich_messages", "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        nodes_by_name["route_intent"],
        [
            "urgent_escalation",
            "compliance_review",
            "sales_pipeline",
            "support_agent",
            "newsletter_batch",
            "general_briefing",
        ],
    )
    builder.add_edge("urgent_escalation", "merge_insights")
    builder.add_edge("compliance_review", "merge_insights")
    builder.add_edge("sales_pipeline", "merge_insights")
    builder.add_edge("newsletter_batch", "merge_insights")
    builder.add_edge("general_briefing", "merge_insights")
    builder.add_conditional_edges(
        "support_agent",
        nodes_by_name["route_support_agent"],
        [
            "zimbra_tools",
            "draft_support_reply",
        ],
    )
    builder.add_edge("zimbra_tools", "support_agent")
    builder.add_edge("draft_support_reply", "merge_insights")
    builder.add_edge("merge_insights", "quality_review")
    builder.add_conditional_edges(
        "quality_review",
        nodes_by_name["route_quality"],
        [
            "refine_output",
            "format_executive_report",
        ],
    )
    builder.add_edge("refine_output", "format_executive_report")
    builder.add_edge("format_executive_report", END)
    builder.set_entry_point("ingest_mailbox")
    return builder
