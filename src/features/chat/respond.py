from draive import (
    ConversationMessage,
    ConversationResponseStream,
    Memory,
    MultimodalContent,
    conversation_completion,
)

from features.knowledge import knowledge_search

__all__ = [
    "chat_respond",
]

CONTEXT_TEMPLATE: str = """\
W kontekście zapytania użytkownika mogą się przydać poniższe informacje:
```
{results}
```
Zignoruj powyższe informacje jeśli nie są na temat.
"""


async def chat_respond(
    instruction: str,
    message: MultimodalContent,
    memory: Memory[list[ConversationMessage], ConversationMessage],
) -> ConversationResponseStream:
    """
    Respond to chat conversation message using provided memory and instruction.
    """

    search_result: str = await knowledge_search(query=message.as_string())
    return await conversation_completion(
        instruction=instruction,  # pass the instruction
        input=MultimodalContent.of(
            # provide optional context from local index
            CONTEXT_TEMPLATE.format(results=search_result) if search_result else "",
            message,  # use the input message
        ),
        memory=memory,  # work in context of given memory
        stream=True,  # and use streaming api
    )
