.PHONY: ingest scan abduct quick ideate ideate-results diagnose analyze export lookup review review-report data-push data-pull test lint

UV ?= uv
RUN = $(UV) run

ingest:
	$(RUN) animedex ingest --list $(LIST)

scan:
	$(RUN) animedex scan

abduct:
	$(RUN) animedex abduct --research --hypothesis-check --scan "$(SCAN)" --gap "$(GAP)" $(if $(N),--n $(N),)

quick:
	$(RUN) animedex quick $(if $(SEED),--seed "$(SEED)",) $(if $(ANOMALY),--anomaly "$(ANOMALY)",) $(if $(FRAMES),--frames-file "$(FRAMES)",) $(if $(FRAME),--frame-id "$(FRAME)",) $(if $(SHOWS),--shows "$(SHOWS)",) $(if $(N),--n $(N),)

ideate:
	$(RUN) animedex ideate $(if $(BRIEF),--brief "$(BRIEF)",) $(if $(MEDIUM),--medium "$(MEDIUM)",) $(if $(N),--n $(N),) $(if $(COMPARE),--compare,)

ideate-results:
	$(RUN) animedex ideate-results --run "$(IDEATION)"

diagnose:
	$(RUN) animedex diagnose $(if $(FILE),--file "$(FILE)",) $(if $(TEXT),--text "$(TEXT)",)

analyze:
	$(RUN) animedex analyze

export:
	$(RUN) animedex export

lookup:
	$(RUN) animedex lookup --id "$(ID)"

review:
	$(RUN) animedex review

review-report:
	$(RUN) animedex review --summary $(if $(DATE),--date $(DATE),)

data-push:
	$(RUN) animedex data push $(if $(TAG),--tag $(TAG),)

data-pull:
	$(RUN) animedex data pull

test:
	$(RUN) pytest -q

lint:
	$(RUN) ruff check .
