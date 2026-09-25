"""Generate the Label Studio interface from the canonical label inventory."""

from __future__ import annotations

import html
import json
from pathlib import Path


def _labels(items: list[dict], control: str, to_name: str) -> str:
    body = "\n".join(
        f'      <Label value="{html.escape(item["name"], quote=True)}" background="#5B8FF9" />'
        for item in items
    )
    return f'<Labels name="{control}" toName="{to_name}" choice="single">\n{body}\n    </Labels>'


def make_label_studio_config(schema_path: str | Path) -> str:
    """Build an importable Label Studio XML config, including current labels."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    classification = "\n".join(
        f'    <Choice value="{html.escape(item["name"], quote=True)}" />'
        for item in schema["classification"]["labels"]
    )
    message_spans = _labels(schema["extraction"]["span_labels"], "message_spans", "current_message")
    subject_spans = _labels(schema["extraction"]["span_labels"], "subject_spans", "subject")
    return f'''<View>
  <Style>
    .source-panel {{ border: 1px solid #d9d9d9; padding: 12px; margin: 8px 0; white-space: pre-wrap; }}
    .htx-text {{ white-space: pre-wrap; }}
  </Style>
  <View class="source-panel">
    <Header value="Subject (span source)" />
    <Text name="subject" value="$subject" />
    {subject_spans}
  </View>
  <View class="source-panel">
    <Header value="Current message (primary span source)" />
    <Text name="current_message" value="$current_message" />
    {message_spans}
  </View>

  <Header value="Thread context (reference for interpretation only)" />
  <Text name="thread_context" value="$thread_context" />
  <Header value="Email metadata (context; do not annotate as text spans)" />
  <View class="source-panel"><Text name="metadata_display" value="$metadata_display" /></View>

  <Header value="Classification: select every supported label. NON_PROJECT must stand alone." />
  <Choices name="review_decision" choice="single" required="true" showInline="true">
    <Choice value="Reviewed" />
    <Choice value="Needs review" />
  </Choices>
  <Choices name="classification" choice="multiple" showInline="true">
{classification}
  </Choices>
  <TextArea name="review_note" toName="current_message" rows="3" editable="true" required="false"
    placeholder="For Needs review, briefly explain what context or evidence is missing." />

  <Header value="Extraction spans: select exact text above and assign one span label per selection." />
  <Text name="span_help" value="Use current message by default. Thread context and metadata are never span sources." />
</View>
'''
