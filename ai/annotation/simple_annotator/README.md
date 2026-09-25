# Simple email annotator

Run commands from the repository root. The project virtual environment already has Flask installed:

```powershell
ai\.venv\Scripts\python.exe ai\annotation\simple_annotator\app.py --reviewer faaiz --pilot project
```

This opens the **Project email pilot**: 50 screened Enron emails, including clear out-of-scope controls. The screening only selected emails for review; it did not assign labels. Each reviewer sees the same 50 emails in the same order. To run another reviewer on the same computer, use `--reviewer reviewer_b --pilot project --port 5001`. The app opens its local browser page automatically.

The new pilot's seed is `ai/data/annotated/human/project_pilot_50/annotation_seed_50.jsonl`. Its reviewer files are saved under `ai/data/annotated/human/project_pilot_50/reviewers/`. Both are ignored by Git. The previous 250-email seed and any saved decisions remain in `ai/data/annotated/human/label_studio_seed/` and `ai/data/annotated/human/simple_annotator/`. To resume that original batch, run:

```powershell
ai\.venv\Scripts\python.exe ai\annotation\simple_annotator\app.py --reviewer faaiz --pilot original --limit 50
```

Read each **current message** and select every applicable classification label. Choose **Not Project Related** only when the message is clearly outside project-management work; choose **Needs another review** if you cannot decide. The app's **What should I label?** card has quick examples. For a text span, click **Add text span**, drag across the exact words in the **Subject** or **Current message** on the left, release the mouse, then choose a span type. Double-click selects one word. If the label menu does not appear, click **Use highlighted text**. You do not need a span when no relevant phrase is present. Use **Needs review** with a short note when the evidence is unclear. Progress saves automatically. Use Previous, Next, or Jump to unfinished; reopening resumes at the first unfinished email.

For label boundaries and examples, read the [annotation guidelines](../annotation_guidelines.md). Label Studio remains available as an alternative. Enron is only a provisional stand-in for real Outlook project mail; evaluate domain fit before using its annotations to train the project model.
