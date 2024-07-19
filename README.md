# Chat

Example of chat using [Bielik](https://huggingface.co/collections/speakleash/bielik-7b-v01-667fd6039d81a28a912ceb1f) running locally with mistralrs.

Built using [draive](https://github.com/miquido/draive) and based on chat example from [draive examples](https://github.com/miquido/draive-examples).

## Setup

To setup the project please use `make venv` command. Python 3.12+ is required, you can specify path tu it by using additional argument `make venv PYTHON_ALIAS=path/to/python`. Default setup requires running Bielik using ollama. Make sure to activate virtual environment by using `. ./.venv/bin/activate`.

Alternatively you can use mistralrs to run the model. To do so you can install it manually or use additional `INSTALL_OPTIONS` parameter when preparing the environment `make venv INSTALL_OPTIONS=".[dev,mistralrs]"`. This setup requires to have rust compiler installed. You can install it by using `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh` command. 

## Run

When the environment is ready you can use `make run` command to run the chat. Make sure to provide all environment variables before running.

## Speedup

Instead of using dependency to [`mistralrs`](https://github.com/EricLBuehler/mistral.rs) use one one of its flavors depending on your machine capabilities. Default version uses CPU to run models.