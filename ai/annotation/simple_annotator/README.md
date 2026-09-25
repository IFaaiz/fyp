# Simple email annotator

Run these commands from the repository root. Install Flask once:

```powershell
python -m pip install "Flask>=3.1,<4"
```

Start the first 50-email pilot:

```powershell
python ai/annotation/simple_annotator/app.py --reviewer faaiz --limit 50
```

If Windows says `python` was not found and the project virtual environment exists, run `ai\.venv\Scripts\python.exe ai\annotation\simple_annotator\app.py --reviewer faaiz --limit 50` from the repository root instead.

For the second independent reviewer, use `--reviewer reviewer_b`. If both apps run on one computer at the same time, add `--port 5001` to the second command. The app opens its local browser page automatically.

Read each **current message** and select every applicable classification label. For a text span, click **Add text span**, drag across the exact words in the **Subject** or **Current message** on the left, release the mouse, then choose a span type. Double-click selects one word. If the label menu does not appear, click **Use highlighted text**. You do not need a span when no relevant phrase is present. Use **Needs review** with a short note when the evidence is unclear. Progress saves automatically. Use Previous, Next, or Jump to unfinished; reopening resumes at the first unfinished email.

After the 50-email pilot, omit `--limit 50` to continue through the remaining records. The original 250-email seed and its order stay fixed. Reviewer results are saved separately under `ai/data/annotated/human/simple_annotator/` and are ignored by Git.

For label boundaries and examples, read the [annotation guidelines](../annotation_guidelines.md). Label Studio remains available as an alternative.
