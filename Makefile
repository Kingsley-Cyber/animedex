.PHONY: validate build clean-build test eval smoke schemas lint ideas packet analyze backfill census review batch status timing recalibrate data-push data-pull

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
