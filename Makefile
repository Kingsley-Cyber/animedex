.PHONY: mcp validate build clean-build test eval smoke schemas lint ideas packet analyze backfill census review review-report batch status timing recalibrate data-push data-pull audit audit-report diagnose backtest stats

UV ?= uv
RUN = $(UV) run

validate:
	$(RUN) animedex validate

build:
	$(RUN) animedex build

clean-build:
	rm -rf build
	$(RUN) animedex build --verify-determinism

test:
	$(RUN) pytest -q

eval:
	$(RUN) animedex eval

smoke:
	$(RUN) animedex smoke $(if $(TITLE),--title $(TITLE),)

schemas:
	$(RUN) animedex schemas

lint:
	$(RUN) ruff check .

analyze:
	$(RUN) animedex analyze

ideas:
	$(RUN) animedex ideate $(if $(ARM),--arm $(ARM),)

packet:
	$(RUN) animedex packet

audit:
	$(RUN) animedex audit $(if $(DATE),--date $(DATE),)

audit-report:
	$(RUN) animedex audit-report

ingest:
	$(RUN) animedex ingest --list $(LIST)

quick:
	$(RUN) animedex quick --seed "$(SEED)" $(if $(SHOWS),--shows "$(SHOWS)",) $(if $(N),--n $(N),)

diagnose:
	$(RUN) animedex diagnose $(if $(FILE),--file "$(FILE)",) $(if $(TEXT),--text "$(TEXT)",)

backtest:
	$(RUN) animedex backtest $(if $(LIST),--list $(LIST),)

stats:
	$(RUN) animedex stats

backfill:
	$(RUN) animedex backfill --list $(LIST) $(if $(BATCH),--batch $(BATCH),)

census:
	$(RUN) animedex census --top $(if $(TOP),$(TOP),500)

review:
	$(RUN) animedex review

review-report:
	$(RUN) animedex review --summary $(if $(DATE),--date $(DATE),)

timing:
	$(RUN) animedex timing

recalibrate:
	$(RUN) animedex recalibrate $(if $(PAIRS),--pairs $(PAIRS),)

batch:
	$(RUN) animedex batch start $(FILE)

status:
	$(RUN) animedex batch status $(NAME)

data-push:
	$(RUN) animedex data push $(if $(TAG),--tag $(TAG),)

data-pull:
	$(RUN) animedex data pull

mcp:
	$(RUN) animedex mcp
