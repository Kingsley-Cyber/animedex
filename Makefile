.PHONY: validate build clean-build test eval smoke schemas lint ideas packet analyze backfill census review batch status timing data-push data-pull audit audit-report diagnose

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

diagnose:
	$(RUN) animedex diagnose $(if $(FILE),--file "$(FILE)",) $(if $(TEXT),--text "$(TEXT)",)

backfill:
	$(RUN) animedex backfill --list $(LIST) $(if $(BATCH),--batch $(BATCH),)

census:
	$(RUN) animedex census --top $(if $(TOP),$(TOP),500)

review:
	$(RUN) animedex review

timing:
	$(RUN) animedex timing

batch:
	$(RUN) animedex batch start $(FILE)

status:
	$(RUN) animedex batch status $(NAME)

data-push:
	$(RUN) animedex data push $(if $(TAG),--tag $(TAG),)

data-pull:
	$(RUN) animedex data pull
