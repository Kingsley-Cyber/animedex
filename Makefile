.PHONY: validate build clean-build test eval smoke schemas lint ideas packet analyze backfill census review

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
	$(RUN) animedex ideate

packet:
	$(RUN) animedex packet

backfill:
	$(RUN) animedex backfill --list $(LIST) $(if $(BATCH),--batch $(BATCH),)

census:
	$(RUN) animedex census --top $(if $(TOP),$(TOP),500)

review:
	$(RUN) animedex review

timing:
	uv run animedex timing
