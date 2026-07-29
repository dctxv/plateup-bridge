r"""
A behaviour-cloned policy for the steak service task. NumPy only.

    python python/policy.py train runs/datasets/reference.npz runs/policies/bc.npz
    python python/policy.py report runs/policies/bc.npz runs/datasets/reference.npz
    python python/policy.py play runs/policies/bc.npz --episodes 10

Specification section 10.3 puts behavioural cloning of per-axis movement and
button edges first in the motor training order. This is that step, kept small
and dependency-free on purpose: one hidden layer, factored heads, Adam, and no
framework. It is enough to establish that observation encoding, action space,
dataset and evaluation all fit together, and it is a checkpoint the later
DAgger and RL stages can start from rather than a finished controller.

The architecture matches the action space rather than fighting it. Section 7.1
specifies per-axis movement and independent button bits, so the policy has one
softmax head per axis and one per button over a shared trunk. Heads are
independent given the trunk, which is exactly the factorisation the action
space already assumes.

Two measurement traps this module tries not to fall into.

**Accuracy is not the metric.** The reference controller stands still most of
the time, so `move_x` is neutral in 80% of frames and a policy that never
moves scores 80%. Balanced accuracy per head is reported alongside raw
accuracy, and the number that actually decides anything is the rollout: how
many groups the policy serves.

**Validation splits by episode.** Consecutive frames are nearly identical, so
splitting by frame leaks the answer across the boundary. `Dataset.split`
holds out whole episodes.
"""

import argparse
import json
import os
import sys
import time

import numpy

import dataset as DATA
import env as ENV

VERSION = "policy_0.1"


def softmax(logits):
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponential = numpy.exp(shifted)
    return exponential / exponential.sum(axis=1, keepdims=True)


class ClonedPolicy:
    """One hidden layer, one softmax head per action component."""

    # Heads whose class frequencies are rebalanced during training. The two
    # movement axes only; see `_class_weights`.
    MOVEMENT_HEADS = (0, 1)

    def __init__(self, input_size, head_sizes, hidden=128, seed=0,
                 balanced_heads=None, balance_power=0.5):
        self.input_size = int(input_size)
        self.head_sizes = list(head_sizes)
        self.balanced_heads = frozenset(
            self.MOVEMENT_HEADS if balanced_heads is None else balanced_heads)
        # How hard to rebalance a movement head. 1.0 is full inverse
        # frequency, 0.0 is none, 0.5 is the square root of the inverse. Full
        # inverse weighting over-corrects once the neutral class dominates
        # heavily -- with randomised starts the neutral share rose from 80% to
        # 94% and the policy stopped predicting it at all -- so the exponent
        # is a measured setting rather than a fixed one.
        self.balance_power = float(balance_power)
        self.hidden = int(hidden)
        self.seed = int(seed)
        generator = numpy.random.default_rng(seed)

        scale = numpy.sqrt(1.0 / max(1, self.input_size))
        self.w1 = (generator.standard_normal((self.input_size, self.hidden))
                   * scale).astype(numpy.float64)
        self.b1 = numpy.zeros(self.hidden)
        head_scale = numpy.sqrt(1.0 / max(1, self.hidden))
        self.w2 = [
            (generator.standard_normal((self.hidden, size)) * head_scale)
            for size in self.head_sizes]
        self.b2 = [numpy.zeros(size) for size in self.head_sizes]

        # Input standardisation, learned from the training split so evaluation
        # cannot see it.
        self.mean = numpy.zeros(self.input_size)
        self.scale = numpy.ones(self.input_size)
        # Classes actually observed per head during training. A head whose
        # data contains one value only has no evidence for the other, and
        # emitting it is a guess, not a decision.
        self.observed = [
            numpy.ones(size, dtype=bool) for size in self.head_sizes]
        self.manifest = {}

    # -- forward ----------------------------------------------------------

    def _standardise(self, observations):
        return (numpy.asarray(observations, dtype=numpy.float64)
                - self.mean) / self.scale

    def _forward(self, standardised):
        hidden = numpy.tanh(standardised @ self.w1 + self.b1)
        logits = [hidden @ w + b for w, b in zip(self.w2, self.b2)]
        return hidden, logits

    def probabilities(self, observations):
        _hidden, logits = self._forward(self._standardise(observations))
        masked = []
        for head, allowed in zip(logits, self.observed):
            if not allowed.all():
                head = numpy.where(allowed, head, -numpy.inf)
            masked.append(softmax(head))
        return masked

    def act(self, observation, generator=None, temperature=0.0):
        """One action for one observation.

        Greedy by default. Specification section 17 requires evaluation
        without exploration noise, so sampling is opt-in and the temperature
        used is recorded by the caller.
        """
        probabilities = self.probabilities(
            numpy.asarray(observation, dtype=numpy.float64)[None, :])
        action = []
        for head in probabilities:
            row = head[0]
            if temperature > 0.0 and generator is not None:
                adjusted = numpy.power(numpy.maximum(row, 1e-12),
                                       1.0 / temperature)
                adjusted /= adjusted.sum()
                action.append(int(generator.choice(len(adjusted),
                                                   p=adjusted)))
            else:
                action.append(int(numpy.argmax(row)))
        return action

    # -- training ---------------------------------------------------------

    def fit(self, data, epochs=30, batch=256, learning_rate=1e-3,
            weight_decay=1e-5, balance=True, seed=0, validation=None,
            verbose=True):
        generator = numpy.random.default_rng(seed)
        observations = numpy.asarray(data.inputs, dtype=numpy.float64)
        actions = numpy.asarray(data.actions, dtype=numpy.int64)

        self.mean = observations.mean(axis=0)
        spread = observations.std(axis=0)
        # A constant feature has no information; dividing by its zero spread
        # would produce NaNs that quietly poison every weight.
        self.scale = numpy.where(spread < 1e-6, 1.0, spread)
        standardised = self._standardise(observations)

        # A class the expert never chose is not a class the policy may emit.
        # Measured: the reference controller never used StopMoving, so its
        # label was constant, and cross-entropy still left the unused logit
        # able to win at out-of-distribution states. The policy pressed
        # StopMoving in 18% of on-policy frames, which disables walking
        # entirely -- a stall caused by a class that had no evidence behind
        # it. This is a statement about the training distribution, recorded in
        # the manifest, not an affordance oracle over gameplay legality.
        self.observed = []
        for head, size in enumerate(self.head_sizes):
            counts = numpy.bincount(actions[:, head], minlength=size)
            self.observed.append(counts > 0)

        weights = self._class_weights(actions) if balance else None

        parameters = [self.w1, self.b1] + self.w2 + self.b2
        moments = [numpy.zeros_like(p) for p in parameters]
        velocities = [numpy.zeros_like(p) for p in parameters]
        beta1, beta2, epsilon = 0.9, 0.999, 1e-8
        step = 0
        history = []

        count = len(standardised)
        for epoch in range(epochs):
            order = generator.permutation(count)
            total = 0.0
            batches = 0
            for start in range(0, count, batch):
                index = order[start:start + batch]
                loss, gradients = self._loss_and_gradients(
                    standardised[index], actions[index], weights,
                    weight_decay)
                total += loss
                batches += 1
                step += 1
                for slot, (parameter, gradient) in enumerate(
                        zip(parameters, gradients)):
                    moments[slot] = (beta1 * moments[slot]
                                     + (1 - beta1) * gradient)
                    velocities[slot] = (beta2 * velocities[slot]
                                        + (1 - beta2) * gradient * gradient)
                    corrected_m = moments[slot] / (1 - beta1 ** step)
                    corrected_v = velocities[slot] / (1 - beta2 ** step)
                    parameter -= learning_rate * corrected_m / (
                        numpy.sqrt(corrected_v) + epsilon)

            record = {"epoch": epoch, "loss": total / max(1, batches)}
            if validation is not None and len(validation):
                scores = self.score(validation)
                record["validation_accuracy"] = scores["mean_accuracy"]
                record["validation_balanced"] = scores["mean_balanced"]
            history.append(record)
            if verbose and (epoch % max(1, epochs // 10) == 0
                            or epoch == epochs - 1):
                extra = ""
                if "validation_accuracy" in record:
                    extra = (f"  val acc {record['validation_accuracy']:.3f}"
                             f"  balanced {record['validation_balanced']:.3f}")
                print(f"  epoch {epoch:3d}  loss {record['loss']:.4f}{extra}")
        return history

    def _class_weights(self, actions):
        """Inverse-frequency weights, on the movement heads only.

        Movement classes are a discretised continuum and every one of them is
        a real intention, so the neutral class dominating the data would
        otherwise teach the policy to stand still. Balancing helps there.

        On a button it is actively harmful, and the failure is worth
        recording. Grab is pressed in 1.9% of frames, so inverse-frequency
        weighting multiplies those by roughly 26 and the policy learns to buy
        recall with false positives. Measured: a balanced clone pressed grab
        in 36% of frames instead of 2%, which put the chef in a loop taking a
        plate and putting it straight back for an entire modelled day, at
        99.0% balanced accuracy. The base rate of a button *is* the signal.
        """
        weights = []
        for head, size in enumerate(self.head_sizes):
            if head not in self.balanced_heads:
                weights.append(numpy.ones(size))
                continue
            counts = numpy.bincount(actions[:, head], minlength=size)
            safe = numpy.where(counts == 0, 1, counts)
            weight = (counts.sum() / (size * safe)) ** self.balance_power
            weight = numpy.where(counts == 0, 0.0, weight)
            weights.append(weight)
        return weights

    def _loss_and_gradients(self, standardised, actions, weights, decay):
        count = len(standardised)
        hidden = numpy.tanh(standardised @ self.w1 + self.b1)

        loss = 0.0
        grad_w2 = []
        grad_b2 = []
        grad_hidden = numpy.zeros_like(hidden)
        active = 0

        for head, size in enumerate(self.head_sizes):
            # A head whose data contains one class has nothing to learn, and
            # training it is actively harmful: cross-entropy drives the unused
            # logit toward negative infinity forever, and that gradient flows
            # back through the shared trunk. Measured: with three such heads
            # out of seven, roughly three sevenths of the trunk's gradient was
            # spent on a boundary that does not exist, and movement accuracy
            # collapsed from 0.978 to 0.179 -- below chance on the dominant
            # class. Inference masks these heads anyway.
            if self.observed[head].sum() <= 1:
                grad_w2.append(numpy.zeros_like(self.w2[head]))
                grad_b2.append(numpy.zeros_like(self.b2[head]))
                continue
            active += 1
            logits = hidden @ self.w2[head] + self.b2[head]
            probabilities = softmax(logits)
            labels = actions[:, head]
            sample_weight = (
                weights[head][labels] if weights is not None
                else numpy.ones(count))
            picked = probabilities[numpy.arange(count), labels]
            loss += -numpy.sum(
                sample_weight * numpy.log(numpy.maximum(picked, 1e-12)))

            delta = probabilities.copy()
            delta[numpy.arange(count), labels] -= 1.0
            delta *= sample_weight[:, None]
            delta /= count

            grad_w2.append(hidden.T @ delta + decay * self.w2[head])
            grad_b2.append(delta.sum(axis=0))
            grad_hidden += delta @ self.w2[head].T

        loss /= count * max(1, active)
        grad_pre = grad_hidden * (1.0 - hidden * hidden)
        grad_w1 = standardised.T @ grad_pre + decay * self.w1
        grad_b1 = grad_pre.sum(axis=0)
        return loss, [grad_w1, grad_b1] + grad_w2 + grad_b2

    # -- scoring ----------------------------------------------------------

    def score(self, data):
        observations = numpy.asarray(data.inputs, dtype=numpy.float64)
        actions = numpy.asarray(data.actions, dtype=numpy.int64)
        probabilities = self.probabilities(observations)

        per_head = []
        for head, size in enumerate(self.head_sizes):
            predicted = numpy.argmax(probabilities[head], axis=1)
            labels = actions[:, head]
            accuracy = float((predicted == labels).mean())
            recalls = []
            for value in range(size):
                mask = labels == value
                if mask.sum():
                    recalls.append(float((predicted[mask] == value).mean()))
            per_head.append({
                "accuracy": accuracy,
                "balanced_accuracy": (
                    float(numpy.mean(recalls)) if recalls else None),
                "classes_present": len(recalls),
                # For a button, how often it fires versus how often it should.
                # A ratio far from 1 is the failure balanced accuracy hides.
                "predicted_positive_rate": float((predicted > 0).mean()),
                "label_positive_rate": float((labels > 0).mean()),
            })
        return {
            "samples": len(observations),
            "per_head": per_head,
            "mean_accuracy": float(
                numpy.mean([h["accuracy"] for h in per_head])),
            "mean_balanced": float(numpy.mean([
                h["balanced_accuracy"] for h in per_head
                if h["balanced_accuracy"] is not None])),
        }

    # -- persistence ------------------------------------------------------

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "w1": self.w1, "b1": self.b1,
            "mean": self.mean, "scale": self.scale,
        }
        for index, (w, b) in enumerate(zip(self.w2, self.b2)):
            payload[f"w2_{index}"] = w
            payload[f"b2_{index}"] = b
            payload[f"observed_{index}"] = self.observed[index]
        manifest = dict(self.manifest)
        manifest.update({
            "schema": VERSION,
            "input_size": self.input_size,
            "head_sizes": self.head_sizes,
            "hidden": self.hidden,
            "seed": self.seed,
            "balanced_heads": sorted(self.balanced_heads),
            "balance_power": self.balance_power,
        })
        payload["manifest"] = json.dumps(manifest, sort_keys=True)
        numpy.savez_compressed(path, **payload)
        return os.path.normpath(path)

    @classmethod
    def load(cls, path):
        with numpy.load(path, allow_pickle=False) as payload:
            manifest = json.loads(str(payload["manifest"]))
            if manifest.get("schema") != VERSION:
                raise ValueError(
                    f"{path}: policy schema {manifest.get('schema')!r} "
                    f"!= {VERSION!r}")
            policy = cls(
                manifest["input_size"], manifest["head_sizes"],
                hidden=manifest["hidden"], seed=manifest.get("seed", 0),
                balanced_heads=manifest.get("balanced_heads"),
                balance_power=manifest.get("balance_power", 1.0))
            policy.w1 = payload["w1"]
            policy.b1 = payload["b1"]
            policy.mean = payload["mean"]
            policy.scale = payload["scale"]
            policy.w2 = [
                payload[f"w2_{index}"]
                for index in range(len(manifest["head_sizes"]))]
            policy.b2 = [
                payload[f"b2_{index}"]
                for index in range(len(manifest["head_sizes"]))]
            policy.observed = [
                payload[f"observed_{index}"]
                if f"observed_{index}" in payload.files
                else numpy.ones(size, dtype=bool)
                for index, size in enumerate(manifest["head_sizes"])]
            policy.manifest = manifest
            return policy


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def head_sizes():
    return [len(ENV.MOVE_VALUES), len(ENV.MOVE_VALUES)] + [2] * len(
        ENV.BUTTONS)


def train(path, output, epochs=30, hidden=128, seed=0, batch=256,
          learning_rate=1e-3, balance=True, holdout=0.25, verbose=True,
          balance_power=0.5):
    data = DATA.Dataset.load(path)
    training, validation = data.split(fraction=holdout, seed=seed)
    if verbose:
        print(f"{len(training)} training samples, {len(validation)} held out "
              f"({len(set(validation.episodes.tolist()))} episodes)")

    policy = ClonedPolicy(
        data.inputs.shape[1], head_sizes(), hidden=hidden, seed=seed,
        balance_power=balance_power)
    started = time.monotonic()
    history = policy.fit(
        training, epochs=epochs, batch=batch, learning_rate=learning_rate,
        balance=balance, seed=seed, validation=validation, verbose=verbose)
    policy.manifest = {
        "trained_from": os.path.normpath(path),
        "dataset_schema": data.manifest.get("schema"),
        "dataset_source": data.manifest.get("source"),
        "obs_schema": data.manifest.get("obs_schema"),
        "act_schema": data.manifest.get("act_schema"),
        "goal_conditioned": bool(data.goal_conditioned),
        "observation_size": int(data.observations.shape[1]),
        "goal_size": int(data.goals.shape[1]),
        "training_samples": len(training),
        "validation_samples": len(validation),
        "epochs": epochs,
        "hidden": hidden,
        "balanced": balance,
        "balance_power": balance_power,
        "observed_classes": [
            int(mask.sum()) for mask in policy.observed],
        "seconds": round(time.monotonic() - started, 1),
        "final_loss": history[-1]["loss"] if history else None,
        "warning": data.manifest.get("warning"),
    }
    if output:
        policy.save(output)
    return policy, data, training, validation, history


def report(policy, data):
    lines = [f"{VERSION}  hidden {policy.hidden}  "
             f"trained from {policy.manifest.get('trained_from')}"]
    names = ["move_x", "move_y"] + list(ENV.BUTTONS)
    scores = policy.score(data)
    lines.append(f"  samples {scores['samples']}")
    lines.append(f"  {'head':<14}{'accuracy':>10}{'balanced':>10}"
                 f"{'fires':>9}{'should':>9}")
    for name, head in zip(names, scores["per_head"]):
        balanced = head["balanced_accuracy"]
        lines.append(
            f"  {name:<14}{head['accuracy']:>10.3f}"
            f"{(balanced if balanced is not None else float('nan')):>10.3f}"
            f"{head['predicted_positive_rate']:>9.3f}"
            f"{head['label_positive_rate']:>9.3f}")
    lines.append(f"  {'mean':<14}{scores['mean_accuracy']:>10.3f}"
                 f"{scores['mean_balanced']:>10.3f}")
    lines.append("  Accuracy is diagnostic only. What decides anything is "
                 "how many groups a rollout serves.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    trainer = subparsers.add_parser("train")
    trainer.add_argument("dataset")
    trainer.add_argument("output")
    trainer.add_argument("--epochs", type=int, default=30)
    trainer.add_argument("--hidden", type=int, default=128)
    trainer.add_argument("--seed", type=int, default=0)
    trainer.add_argument("--batch", type=int, default=256)
    trainer.add_argument("--lr", type=float, default=1e-3, dest="lr")
    trainer.add_argument("--no-balance", action="store_true")
    trainer.add_argument("--balance-power", type=float, default=0.5,
                         dest="balance_power")
    trainer.add_argument("--json", dest="json_path")

    reporter = subparsers.add_parser("report")
    reporter.add_argument("policy")
    reporter.add_argument("dataset")

    player = subparsers.add_parser("play")
    player.add_argument("policy")
    player.add_argument("--episodes", type=int, default=5)
    player.add_argument("--layout",
                        default=os.path.join("runs", "demos", "smoke.jsonl"))

    args = parser.parse_args()

    if args.command == "train":
        policy, data, training, validation, history = train(
            args.dataset, args.output, epochs=args.epochs,
            hidden=args.hidden, seed=args.seed, batch=args.batch,
            learning_rate=args.lr, balance=not args.no_balance,
            balance_power=args.balance_power)
        print()
        print("training split:")
        print(report(policy, training))
        print()
        print("held-out split:")
        print(report(policy, validation))
        print("\nwrote " + os.path.normpath(args.output))
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump({
                    "manifest": policy.manifest,
                    "history": history,
                    "training": policy.score(training),
                    "validation": policy.score(validation),
                }, output, indent=2, sort_keys=True)
            print("wrote " + os.path.normpath(args.json_path))
        return 0

    if args.command == "report":
        policy = ClonedPolicy.load(args.policy)
        print(report(policy, DATA.Dataset.load(args.dataset)))
        return 0

    import evaluate
    policy = ClonedPolicy.load(args.policy)
    results = evaluate.rollout_any(
        policy, layout=args.layout, episodes=args.episodes)
    print(evaluate.describe(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
