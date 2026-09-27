.PHONY: ingest quick diagnose analyze export review review-report data-push data-pull test lint

UV ?= uv
RUN = $(UV) run

ingest:
	$(RUN) animedex ingest --list $(LIST)

quick:
	$(RUN) animedex quick --seed "$(SEED)" $(if $(SHOWS),--shows "$(SHOWS)",) $(if $(N),--n $(N),)

diagnose:
	$(RUN) animedex diagnose $(if $(FILE),--file "$(FILE)",) $(if $(TEXT),--text "$(TEXT)",)

analyze:
	$(RUN) animedex analyze

export:
	$(RUN) animedex export

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
