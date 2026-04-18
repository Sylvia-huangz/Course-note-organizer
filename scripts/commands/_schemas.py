from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommandError(BaseModel):
    code: str
    message: str
    suggestions: list[str] = Field(default_factory=list)
    retryable: bool = False
    details: dict[str, Any] | None = None


class CommandManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "error", "preview", "deleted", "no_relevant_context_found"]
    notes: list[str] = Field(default_factory=list)
    error: CommandError | None = None


class TranscriptSegment(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str = ""


class TranscriptPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    segments: list[TranscriptSegment] = Field(default_factory=list)
    text: str = ""
    language: str | None = None
    model: str | None = None


class SourceExcerpt(BaseModel):
    path: str
    matched_lines: list[str] = Field(default_factory=list)


class MatchCandidate(BaseModel):
    line: str
    overlap_score: int


class CanvasContextPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    course_title: str
    lesson_title: str | None = None
    sources: list[SourceExcerpt] = Field(default_factory=list)
    announcements: list[str] = Field(default_factory=list)
    assignments: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    match_candidates: list[MatchCandidate] = Field(default_factory=list)
    status: Literal["ok", "no_relevant_context_found", "error"] = "ok"
    notes: list[str] = Field(default_factory=list)
    error: CommandError | None = None


class TopicIndexItem(BaseModel):
    timestamp: str = ""
    topic: str = ""
    subtopic: str = ""
    section_ref: str = ""


class RepairAnnotation(BaseModel):
    type: str = "context-assisted"
    note: str = ""


class ExampleSpec(BaseModel):
    title: str = "Worked example"
    content: str = ""


class NoteSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    section_ref: str = ""
    title: str = ""
    sources: list[str] = Field(default_factory=list)
    content: str = ""
    key_points: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    repair_annotations: list[RepairAnnotation] = Field(default_factory=list)
    examples: list[ExampleSpec] = Field(default_factory=list)
    question: str | None = None


class CanvasContextNote(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary_lines: list[str] = Field(default_factory=list)
    relevance_lines: list[str] = Field(default_factory=list)


class SummarySpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    overview: str | None = None
    key_takeaways: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    review_steps: list[str] = Field(default_factory=list)


class MetadataSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    course_title: str | None = None
    lesson_title: str | None = None
    keywords: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    estimated_review_time_minutes: int | None = None
    timeline_topics: list[dict[str, Any]] = Field(default_factory=list)
    exam_assignment_relevance: list[str] = Field(default_factory=list)
    repair_annotations_present: bool | None = None


class NoteSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    course_title: str
    lesson_title: str | None = None
    note_style: str | None = None
    video_topic_index: list[TopicIndexItem] = Field(default_factory=list)
    canvas_context: CanvasContextNote = Field(default_factory=CanvasContextNote)
    sections: list[NoteSection] = Field(default_factory=list)
    summary: SummarySpec = Field(default_factory=SummarySpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)


class InspectCanvasContextRequest(BaseModel):
    course_title: str
    lesson_title: str | None = None
    input_paths: list[str] = Field(min_length=1)
    output: str


class ExtractCanvasAudioRequest(BaseModel):
    course_title: str
    source: str
    base_dir: str = "."
    ffmpeg_path: str | None = None
    output_name: str | None = None
    manifest: str | None = None


class TranscribeAudioRequest(BaseModel):
    course_title: str
    base_dir: str = "."
    audio: str | None = None
    caption_file: str | None = None
    model: str = "base"
    language: str | None = None
    initial_prompt: str | None = None
    manifest: str | None = None

    @model_validator(mode="after")
    def check_sources(self) -> "TranscribeAudioRequest":
        if not self.audio and not self.caption_file:
            raise ValueError("Provide either audio or caption_file.")
        return self


class RemoteTranscriptionRequest(BaseModel):
    course_title: str
    base_dir: str = "."
    audio: str
    manifest: str | None = None


class OpenAITranscriptionRequest(RemoteTranscriptionRequest):
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "whisper-1"
    language: str | None = None
    prompt: str | None = None


class AssemblyAITranscriptionRequest(RemoteTranscriptionRequest):
    api_key_env: str = "ASSEMBLYAI_API_KEY"
    base_url: str = "https://api.assemblyai.com"
    poll_interval: float = 3.0
    timeout_seconds: float = 600.0
    language_code: str | None = None


class DeepgramTranscriptionRequest(RemoteTranscriptionRequest):
    api_key_env: str = "DEEPGRAM_API_KEY"
    model: str = "nova-3"
    language: str | None = None


class CleanupRequest(BaseModel):
    course_root: str
    path: list[str] = Field(min_length=1)
    confirm_delete: bool = False
    manifest: str | None = None


class AssembleNotesRequest(BaseModel):
    spec: str
    course_title: str | None = None
    base_dir: str = "."
    style: str = "standard-structured"
    output: str | None = None
    metadata_sidecar: str | None = None
    manifest: str | None = None


class OrchestrateRequest(BaseModel):
    spec: str
    course_title: str
    base_dir: str = "."
    style: str = "standard-structured"
    export_format: Literal["markdown", "docx", "pdf", "all"] = "markdown"
    manifest: str | None = None


class ExportDocxRequest(BaseModel):
    markdown: str
    output: str
    manifest: str | None = None


class ExportDocxResult(BaseModel):
    status: Literal["ok"]
    output: str
    formula_strategy: str
    notes: list[str] = Field(default_factory=list)


class ExportPdfRequest(BaseModel):
    markdown: str
    output: str
    manifest: str | None = None


class ExportPdfResult(BaseModel):
    status: Literal["ok"]
    output: str
