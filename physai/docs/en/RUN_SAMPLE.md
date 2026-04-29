# Running the Sample Project

This document walks you through using a sample project to learn how to use the physai platform.

The bundled SO-101 + GR00T sample under `examples/so101-gr00t/` ships four
ready-to-run configs (`{liftcube,pickorange} × {gr00t-n1.5,gr00t-n1.6}`). All
four run a three-stage pipeline by default: `convert` reads raw HDF5
demonstrations and writes a LeRobot v2.1 dataset; `train` fine-tunes the
GR00T policy on that dataset; `eval` runs the trained policy in LeIsaac and
records metrics.

This walkthrough shows two ways to use the sample:

- **Path A — Public LeRobot dataset.** The Lightwheel AI public PickOrange
  dataset is already in LeRobot v2.1 format, so the `convert` stage isn't
  needed and the pipeline starts from `train`. Fastest path to a first run.
- **Path B — Your own HDF5 demos.** Start from raw Isaac Lab / LeIsaac HDF5
  recordings; the pipeline runs end-to-end including `convert`. Requires one
  extra container to build (the CPU-side converter).

Both paths share the same CLI install and most of the container builds.

## Installing and Configuring the physai CLI

We recommend using Python in a virtual environment using tools like [uv venv](https://docs.astral.sh/uv/pip/environments/) rather than installing it in your system environment.

```bash
# cd into physai/ first:

pip install -e cli
```

Configure the CLI:

```bash
mkdir -p ~/.physai && cat > ~/.physai/config.yaml <<EOF
host: physai-login
model_config_roots:
  - $(pwd)/examples/so101-gr00t/model_configs
EOF
```

`~/.physai/config.yaml` is the configuration file referenced when using the `physai` command. Both values can be overridden with command-line arguments at runtime:

- `--host HOST` overrides `host`
- `--model-config-root PATH` prepends to `model_config_roots` (can be specified multiple times)

If you only use one host and one model-config root, setting them here eliminates the need for flags.

## Building Containers

Containers on the cluster are built and run using **Enroot** (a lightweight, rootless container runtime) and **Pyxis** (a Slurm plugin that enables Enroot via `srun --container-image=...`). Here are two key concepts:

- **Image** — A build artifact. A squashfs file located at `/fsx/enroot/<name>.sqsh`. Each `physai build` produces one image. Images are immutable, shared across jobs, and persist until you `--rebuild` or delete the file.
- **Container** — A live runtime instance of an image. Created on a worker node at job start and typically destroyed when the job ends. Containers may remain if a job terminates abnormally. Use `physai clean --enroot` to remove stale containers.

`physai build` generates images used in the pipeline. Image builds are
executed as Slurm jobs. The full set takes roughly 30–40 minutes; once each
`/fsx/enroot/<name>.sqsh` exists, `physai build` refuses to redo it unless
you pass `--rebuild`.

The base runtime + the GR00T N1.6 trainer + the N1.6 eval container are needed
for both paths:

```bash
physai build -n examples/so101-gr00t/containers/leisaac-runtime
physai build -n examples/so101-gr00t/containers/leisaac-gr00t-n1.6
physai build -n examples/so101-gr00t/containers/gr00t-n1.6-trainer
```

Path B additionally needs the CPU-side converter:

```bash
physai build -n examples/so101-gr00t/containers/so101-converter
```

`-n` (`--no-stream`) submits the build and returns immediately, so the commands above queue up back-to-back as separate Slurm jobs rather than tying up your terminal. To follow a specific build, use `physai logs <job-id>`. Drop `-n` to stream a build's log live; Ctrl-C then detaches without cancelling the job.

You can view the history of executed jobs with the following command:

```bash
physai list

physai list
JOB_ID   TYPE    NAME                           STATE        SUBMIT (UTC)    START (UTC)     ELAPSED    COMMENT
3        build   leisaac-gr00t-n1.6             PENDING      04-28 09:40:55  N/A             0:00       base=/fsx/enroot/leisaac-runtime.sqsh
2        build   leisaac-runtime                RUNNING      04-28 09:39:35  04-28 09:39:35  2:50       base=nvcr.io/nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04
```

## The Run Config

The pipeline definition is configured in a YAML file. The PickOrange + GR00T N1.6 config is at [examples/so101-gr00t/configs/so101_pickorange_gr00t-n1.6.yaml](../../examples/so101-gr00t/configs/so101_pickorange_gr00t-n1.6.yaml):

```yaml
pipeline:
  stages: [convert, train, eval]

sim:
  platform: leisaac
  environment: LeIsaac-SO101-PickOrange-v0
  mimic_environment: LeIsaac-SO101-PickOrange-Mimic-v0
  language_instruction: "Pick up the orange and place it on the plate"

model:
  name: gr00t-n1.6
  config_dir: gr00t-n1.6/so101-dualcam

stages:
  convert:
    partition: cpu
    container: so101-converter
  train:
    partition: gpu
    gres: "gpu:1"
    constraint: l40s
    container: gr00t-n1.6-trainer
    max_steps: 10000
  eval:
    partition: gpu
    gres: "gpu:1"
    container: leisaac-gr00t-n1.6
    rounds: 20
```

- `pipeline.stages`: Stages to run by default. The CLI's `--from` / `--to` flags narrow this list at runtime.
- `stages.<name>`: Resource and parameter settings for each stage.
- `model.config_dir`: A relative name resolved against `model_config_roots` (see [PIPELINE_DEVELOP.md §4](PIPELINE_DEVELOP.md#4-pipeline-configuration) for the full `run_config.yaml` reference).

## Path A — Run with the public PickOrange LeRobot dataset

This sample uses the [Pick Orange](https://huggingface.co/datasets/LightwheelAI/leisaac-pick-orange) dataset published by Lightwheel AI alongside the [LeIsaac](https://github.com/lightwheelai/leisaac) simulation environment. Since it is already provided in LeRobot v2.1 format (60 episodes, ~36k frames, 698 MB), the `convert` stage is unnecessary — we upload it directly into `/fsx/datasets/` and start the pipeline from `train`.

Download and upload:

```bash
pip install -U huggingface_hub
hf download LightwheelAI/leisaac-pick-orange \
  --repo-type dataset --local-dir /tmp/leisaac-pick-orange
physai upload datasets /tmp/leisaac-pick-orange/
```

The `physai upload datasets` command places the dataset at `/fsx/datasets/leisaac-pick-orange/` on the cluster. Verify with:

```bash
physai ls datasets
```

Start the pipeline from the `train` stage:

```bash
physai run -n --config examples/so101-gr00t/configs/so101_pickorange_gr00t-n1.6.yaml \
  --from train --dataset leisaac-pick-orange
```

The executed pipeline runs as Slurm jobs. You can check progress with:

```bash
physai list
JOB_ID   TYPE    NAME                           STATE        SUBMIT (UTC)    START (UTC)     ELAPSED    COMMENT
5        run     run-20260430-011618/eval       COMPLETED    04-30 01:16:34  04-30 02:50:05  00:44:07
4        run     run-20260430-011618/train      COMPLETED    04-30 01:16:29  04-30 01:16:30  01:33:35
```

## Path B — Run with your own HDF5 demos

Start from raw Isaac Lab / LeIsaac HDF5 recordings. The `convert` stage in the pipeline reads them from `/fsx/raw/<name>/` and writes a LeRobot v2.1 dataset to `/fsx/datasets/<name>/`; the rest of the pipeline then proceeds as in Path A.

Upload your HDF5 directory to S3 (preferred — `/fsx/raw/` is a Data Repository
Association cache that auto-imports from S3 on first access):

```bash
aws s3 cp --recursive /path/to/my-demos/ s3://<data-bucket>/raw/my-demos/
```

You can also rsync directly to `/fsx/raw/` — `physai upload raw` does this — but for any non-trivial dataset the S3 path is faster and resumable.

Run the full pipeline. With `convert` as the first stage, `--raw <name>` is required:

```bash
physai run -n --config examples/so101-gr00t/configs/so101_pickorange_gr00t-n1.6.yaml \
  --raw my-demos
```

By default the converter writes to `/fsx/datasets/my-demos/` (matching the
`--raw` name). Pass `--dataset <name>` to override:

```bash
physai run -n --config ... --raw my-demos --dataset pickorange-baseline
```

For the singlecam LiftCube task, swap to the LiftCube config and use the singlecam model config; the rest of the flow is identical.

## Next steps

This concludes the introduction to using the pipeline with the sample project.
For more detail on the example itself — the full container layout, the four
shipping configs, and how to adapt the pipeline to a new task or robot — see
[examples/so101-gr00t/README.md](../../examples/so101-gr00t/README.md).
