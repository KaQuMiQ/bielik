from asyncio import get_running_loop
from base64 import b64encode
from typing import Any, Final, Literal, cast

from chainlit import (
    Audio,
    ChatProfile,
    ChatSettings,
    Component,
    ErrorMessage,
    File,
    Image,
    Message,
    Pdf,
    Starter,
    Step,
    Text,
    Video,
    on_chat_start,  # type: ignore
    on_message,  # type: ignore
    on_settings_update,  # type: ignore
    set_chat_profiles,  # type: ignore
    set_starters,  # type: ignore
    user_session,
)
from chainlit.input_widget import TextInput
from draive import (
    LMM,
    AudioBase64Content,
    AudioDataContent,
    AudioURLContent,
    ConversationMessage,
    ConversationMessageChunk,
    DataModel,
    ImageBase64Content,
    ImageDataContent,
    ImageURLContent,
    MultimodalContent,
    ScopeDependencies,
    ScopeState,
    TextContent,
    TextEmbedding,
    Tokenization,
    ToolCallStatus,
    VideoBase64Content,
    VideoDataContent,
    VideoURLContent,
    VolatileAccumulativeMemory,
    VolatileVectorIndex,
    ctx,
    load_env,
    setup_logging,
)
from draive.fastembed import FastembedTextConfig, fastembed_text_embedding
from draive.mrs import MRSChatConfig, MRSClient, mrs_lmm_invocation
from features.chat import chat_respond
from features.knowledge import index_pdf
from mistralrs import Architecture, Which

load_env()  # load env first if needed
setup_logging("demo", "metrics")

DEFAULT_TEMPERATURE: float = 0.75
DEFAULT_PROMPT: str = """\
Jesteś przyjaznym botem. Rozmawiaj na wszystkie tematy i bądź miły.

Możesz dostać od użytkownika dodatkowe materiały, użyj ich jeśli są przydatne lub zignoruj.

ZAWSZE ODPOWIADAJ PO POLSKU!
"""

# define dependencies globally - it will be reused for all chats
# regardless of selected service selection
# those are definitions of external services access methods
dependencies: Final[ScopeDependencies] = ScopeDependencies(
    MRSClient(
        models={
            "bielik:7b": Which.Plain(
                model_id="speakleash/Bielik-7B-Instruct-v0.1",
                arch=Architecture.Llama,
                tokenizer_json=None,
                repeat_last_n=64,
            ),
            "bielik:7bQ4": Which.GGUF(
                tok_model_id="speakleash/Bielik-7B-Instruct-v0.1",
                quantized_model_id="speakleash/Bielik-7B-Instruct-v0.1-GGUF",
                quantized_filename="bielik-7b-instruct-v0.1.Q4_K_M.gguf",
                repeat_last_n=64,
            ),
            "bielik:7bQ8": Which.GGUF(
                tok_model_id="speakleash/Bielik-7B-Instruct-v0.1",
                quantized_model_id="speakleash/Bielik-7B-Instruct-v0.1-GGUF",
                quantized_filename="bielik-7b-instruct-v0.1.Q8_0.gguf",
                repeat_last_n=64,
            ),
        }
    ),
)


@set_chat_profiles
def prepare_profiles(user: Any) -> list[ChatProfile]:
    """
    Prepare chat profiles allowing to select service providers
    """

    return [
        ChatProfile(
            name="bielik:7b",
            markdown_description="bielik:7b",
            default=False,
        ),
        ChatProfile(
            name="bielik:7bQ4",
            markdown_description="bielik:7bQ4",
            default=False,
        ),
        ChatProfile(
            name="bielik:7bQ8",
            markdown_description="bielik:7bQ8",
            default=True,
        ),
    ]


@set_starters
def prepare_starters(user: Any) -> list[Starter]:
    """
    List of starter messages for the chat, can be used for a common task shortcuts
    or as a showcase of the implemented features.
    """

    return [
        Starter(
            label="Poezja",
            message="wielkim poetą był... o kim tak mówiono?",
        ),
        Starter(
            label="Co to znaczy?",
            message='Co to znaczy jak ktoś powiedział do mnie "ej weźże no!" ?',
        ),
        Starter(
            label="Powódź",
            message="Czy powódź jest zjawiskiem ekstremalnym?",
        ),
    ]


@on_chat_start
async def prepare() -> None:
    """
    Prepare chat session which includes preparing a set of dependencies
    matching selected profile (services provider) and settings.
    """

    # prepare chat session memory - we are using volatile memory
    # which will return up to 8 last messages to the LLM context
    user_session.set(  # pyright: ignore[reportUnknownMemberType]
        "chat_memory",
        VolatileAccumulativeMemory[ConversationMessage]([], limit=8),
    )
    # select services based on current profile and form a base state for session
    state: ScopeState = ScopeState(
        VolatileVectorIndex(),  # it will be used as a knowledge base
        LMM(invocation=mrs_lmm_invocation),
        FastembedTextConfig(model="nomic-ai/nomic-embed-text-v1.5"),
        # use fake tokenizer
        Tokenization(tokenize_text=lambda text, **extra: [0 for _ in text]),
        TextEmbedding(embed=fastembed_text_embedding),
        MRSChatConfig(
            model=str(user_session.get("chat_profile", "bielik:7bQ4")),  # type: ignore
            temperature=DEFAULT_TEMPERATURE,
        ),
    )

    # use selected services by setting up session state
    user_session.set(  # pyright: ignore[reportUnknownMemberType]
        "state",
        state,
    )

    # prepare system prompt
    user_session.set(  # pyright: ignore[reportUnknownMemberType]
        "system_prompt",
        DEFAULT_PROMPT,
    )

    # prepare available settings
    await ChatSettings(
        [
            TextInput(
                id="system_prompt",
                label="System prompt",
                initial=DEFAULT_PROMPT,
                multiline=True,
            ),
        ]
    ).send()


@on_settings_update
async def update_settings(settings: dict[str, Any]) -> None:
    user_session.set(  # pyright: ignore[reportUnknownMemberType]
        "system_prompt",
        settings.get("system_prompt", DEFAULT_PROMPT),
    )


@on_message
async def message(  # noqa: C901, PLR0912
    message: Message,
) -> None:
    """
    Handle incoming message and stream the response
    """

    # enter a new context for processing each message
    # using session state and shared dependencies
    async with ctx.new(
        "chat",
        state=user_session.get("state"),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        dependencies=dependencies,
    ):
        response_message: Message = Message(author="assistant", content="")
        await response_message.send()  # prepare message for streaming
        try:
            # request a chat conversation completion stream
            response_stream = await chat_respond(
                instruction=user_session.get("system_prompt", DEFAULT_PROMPT),  # pyright: ignore[reportUnknownMemberType, reportArgumentType]
                # convert message from chainlit to draive
                message=await _as_multimodal_content(
                    content=message.content,
                    elements=message.elements,  # pyright: ignore[reportArgumentType]
                ),
                memory=user_session.get("chat_memory"),  # pyright: ignore[reportUnknownMemberType, reportArgumentType]
            )

            # track tools execution to show progress items
            tool_steps: dict[str, Step] = {}
            async for part in response_stream:
                match part:  # consume each incoming stream part
                    case ConversationMessageChunk() as chunk:
                        for element in _as_message_content(chunk.content):
                            match element:
                                case Text() as text:
                                    # for a text message part simply add it to the UI
                                    # this might not be fully accurate but chainlit seems to
                                    # not support it any other way (except custom implementation)
                                    await response_message.stream_token(str(text.content))

                                case other:
                                    # for a media add it separately
                                    response_message.elements.append(other)  # pyright: ignore[reportArgumentType]
                                    await response_message.update()

                    case ToolCallStatus() as tool_status:
                        ctx.log_debug("Received tool status: %s", tool_status)
                        # for a tool status add or update its progress indicator
                        step: Step
                        if current_step := tool_steps.get(tool_status.identifier):
                            step = current_step

                        else:
                            step: Step = Step(
                                id=tool_status.identifier,
                                name=tool_status.tool,
                                type="tool",
                            )
                            tool_steps[tool_status.identifier] = step

                            match tool_status.status:
                                case "STARTED":
                                    await step.send()

                                case "RUNNING":
                                    if content := tool_status.content:
                                        # stream tool update status if provided
                                        await step.stream_token(str(content))

                                case "FINISHED":
                                    # finalize the status
                                    await step.update()

                                case "FAILED":
                                    # finalize indicating an error
                                    step.output = "ERROR"
                                    await step.update()

        except Exception as exc:
            ctx.log_error("Conversation failed", exception=exc)
            # replace the message with the error message as the result
            # not the best error handling but still handling
            await response_message.remove()
            await ErrorMessage(content=str(exc)).send()

        else:
            await response_message.update()  # finalize the message


# helper method for loading data from file
def _load_file_content(path: str) -> bytes:
    with open(path, "rb") as file:
        return file.read()


# async wrapper for the helper method above
async def _load_file_bytes(path: str) -> bytes:
    return await get_running_loop().run_in_executor(
        None,
        _load_file_content,
        path,
    )


# helper for getting base64 data from the local file
async def _load_file_b64(path: str) -> str:
    file_content: bytes = await _load_file_bytes(path)
    return b64encode(file_content).decode("utf-8")


async def _as_multimodal_content(  # noqa: C901, PLR0912
    content: str,
    elements: list[Text | Image | Audio | Video | Pdf | File],
) -> MultimodalContent:
    """
    Convert message content parts from chainlit to draive.
    """

    parts: list[Any] = [content]
    for element in elements:
        match element:
            case Text() as text:
                parts.append(text.content)

            case Image() as image:
                if url := image.url:
                    parts.append(
                        ImageURLContent(
                            image_url=url,
                            mime_type=cast(
                                Literal["image/jpeg", "image/png", "image/gif"],
                                image.mime
                                if image.mime in ["image/jpeg", "image/png", "image/gif"]
                                else None,
                            ),
                        )
                    )

                elif path := image.path:
                    parts.append(
                        ImageBase64Content(
                            image_base64=await _load_file_b64(path),
                            mime_type=cast(
                                Literal["image/jpeg", "image/png", "image/gif"],
                                image.mime
                                if image.mime in ["image/jpeg", "image/png", "image/gif"]
                                else None,
                            ),
                        )
                    )

                else:
                    raise NotImplementedError("Unsupported image content")

            case Audio() as audio:
                if url := audio.url:
                    parts.append(
                        AudioURLContent(
                            audio_url=url,
                            mime_type=audio.mime,
                        )
                    )

                elif path := audio.path:
                    parts.append(
                        AudioBase64Content(
                            audio_base64=await _load_file_b64(path),
                            mime_type=audio.mime,
                        )
                    )

                else:
                    raise NotImplementedError("Unsupported audio content")

            case Video() as video:
                if url := video.url:
                    parts.append(
                        VideoURLContent(
                            video_url=url,
                            mime_type=video.mime,
                        )
                    )

                elif path := video.path:
                    parts.append(
                        VideoBase64Content(
                            video_base64=await _load_file_b64(path),
                            mime_type=video.mime,
                        )
                    )

                else:
                    raise NotImplementedError("Unsupported video content")

            case Pdf() as pdf:
                if path := pdf.path:
                    await index_pdf(source=path)

                else:
                    raise NotImplementedError("Unsupported pdf content")

            case File() as file:
                if path := file.path:
                    if path.endswith(".pdf"):
                        await index_pdf(source=path)

                    elif path.endswith(".mp3"):
                        parts.append(
                            AudioBase64Content(
                                audio_base64=await _load_file_b64(path),
                                mime_type="audio/mp3",
                            )
                        )

                    elif path.endswith(".wav"):
                        parts.append(
                            AudioBase64Content(
                                audio_base64=await _load_file_b64(path),
                                mime_type="audio/wav",
                            )
                        )

                    elif path.endswith(".mp4"):
                        parts.append(
                            VideoBase64Content(
                                video_base64=await _load_file_b64(path),
                                mime_type="video/mp4",
                            )
                        )

                else:
                    raise NotImplementedError("Unsupported file content")

    return MultimodalContent.of(*parts)


def _as_message_content(  # noqa: C901
    content: MultimodalContent,
) -> list[Text | Image | Audio | Video | Component]:
    result: list[Text | Image | Audio | Video | Component] = []
    for part in content.parts:
        match part:
            case TextContent() as text:
                result.append(Text(content=text.text))

            case ImageURLContent() as image_url:
                result.append(Image(url=image_url.image_url))

            case ImageBase64Content():
                raise NotImplementedError("Base64 content is not supported yet")

            case ImageDataContent():
                raise NotImplementedError("Bytes content is not supported yet")

            case AudioURLContent() as audio_url:
                result.append(Audio(url=audio_url.audio_url))

            case AudioBase64Content():
                raise NotImplementedError("Base64 content is not supported yet")

            case AudioDataContent():
                raise NotImplementedError("Bytes content is not supported yet")

            case VideoURLContent() as video_url:
                result.append(Video(url=video_url.video_url))

            case VideoBase64Content():
                raise NotImplementedError("Base64 content is not supported yet")

            case VideoDataContent():
                raise NotImplementedError("Bytes content is not supported yet")

            case DataModel() as data:
                result.append(Component(props=data.as_dict()))

    return result


if __name__ == "__main__":
    from chainlit.cli import run_chainlit

    run_chainlit(__file__)
