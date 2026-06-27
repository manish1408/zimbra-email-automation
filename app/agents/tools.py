from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.email_sync import EmailSyncService


class GetInboxInput(BaseModel):
    user_email: str = Field(description="Mailbox email address")
    limit: int = Field(default=10, description="Max messages to return")


class SearchMessagesInput(BaseModel):
    user_email: str = Field(description="Mailbox email address")
    query: str = Field(description="Zimbra search query, e.g. in:inbox subject:invoice")
    limit: int = Field(default=10, description="Max messages to return")


class GetMessageInput(BaseModel):
    user_email: str = Field(description="Mailbox email address")
    message_id: str = Field(description="Zimbra message ID")


def build_zimbra_tools(email_service: EmailSyncService) -> list[StructuredTool]:
    async def list_mail_users() -> str:
        response = await email_service.list_users()
        users = [
            {"email": user.email, "display_name": user.display_name}
            for user in response.users[:20]
        ]
        return json.dumps({"total": response.total, "users": users}, default=str)

    async def get_inbox(user_email: str, limit: int = 10) -> str:
        response = await email_service.get_inbox(user_email=user_email, limit=limit)
        return json.dumps(
            {
                "user": response.user.email,
                "total": response.total,
                "messages": [message.model_dump(by_alias=True) for message in response.messages],
            },
            default=str,
        )

    async def search_messages(user_email: str, query: str, limit: int = 10) -> str:
        response = await email_service.search_user_messages(
            user_email=user_email,
            query=query,
            limit=limit,
        )
        return json.dumps(
            {
                "user": response.user.email,
                "query": response.query,
                "total": response.total,
                "messages": [message.model_dump(by_alias=True) for message in response.messages],
            },
            default=str,
        )

    async def get_message_body(user_email: str, message_id: str) -> str:
        message = await email_service.get_message(user_email=user_email, message_id=message_id)
        return json.dumps(message.model_dump(by_alias=True), default=str)

    return [
        StructuredTool.from_function(
            coroutine=list_mail_users,
            name="list_mail_users",
            description="List Zimbra mail accounts on the server.",
        ),
        StructuredTool.from_function(
            coroutine=get_inbox,
            name="get_inbox",
            description="Fetch recent inbox messages for a mailbox.",
            args_schema=GetInboxInput,
        ),
        StructuredTool.from_function(
            coroutine=search_messages,
            name="search_messages",
            description="Search messages in a mailbox using Zimbra query syntax.",
            args_schema=SearchMessagesInput,
        ),
        StructuredTool.from_function(
            coroutine=get_message_body,
            name="get_message_body",
            description="Fetch full message content by ID for a mailbox.",
            args_schema=GetMessageInput,
        ),
    ]


async def execute_tool_call(
    email_service: EmailSyncService,
    tool_name: str,
    tool_args: dict[str, Any],
) -> str:
    tools_by_name = {tool.name: tool for tool in build_zimbra_tools(email_service)}
    tool = tools_by_name.get(tool_name)
    if tool is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    return await tool.ainvoke(tool_args)
