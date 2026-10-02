import pytest

from infrastructure.config import ConfigError, StrictModel, load_config


class Sampling(StrictModel):
    temperature: float


class Experiment(StrictModel):
    name: str
    sampling: Sampling


def test_load_config_returns_validated_model(tmp_path):
    path = tmp_path / "experiment.yaml"
    path.write_text("name: baseline\nsampling:\n  temperature: 0.6\n")
    assert load_config(path, Experiment) == Experiment(
        name="baseline", sampling=Sampling(temperature=0.6)
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: x\nsampling: {temperature: 0.6, temprature: 1}\n", "sampling.temprature"),
        ("name: x\nsampling: {temperature: hot}\n", "sampling.temperature"),
        ("name: x\n", "sampling: Field required"),
        ("", "<root>"),
        ("name: [unclosed\n", "invalid YAML"),
    ],
)
def test_load_config_reports_the_offending_key(tmp_path, text, message):
    path = tmp_path / "experiment.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path, Experiment)
