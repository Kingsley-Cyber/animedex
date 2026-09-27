# Gold annotations: rules

These files are the answer key the pipeline is measured against. They only work if they come from your own knowledge of each show.

1. **Only annotate a show you have watched** (inside its scope in `corpus/titles.yaml`). If you haven't seen one, say so and the agent swaps in the approved backup.
2. **Your own words, no AI help.** Don't use Claude, ChatGPT, or any assistant to fill these in. The eval compares the model to your judgment; AI-assisted annotations turn it into AI against AI.
3. **Before any model output for that title.** Don't read partner or gold profiles until your annotations are committed. Live runs on a gold title refuse to start until its file is filled and committed.
4. **When a file is done,** tell the agent "annotations done". It checks the file (`animedex eval`) and commits it for you.

Each `annotation.yaml` needs: the seven key enum fields (allowed values are listed in the comments), 3–5 `load_bearing_elements` in your own words, and `main_engine` as one sentence.
