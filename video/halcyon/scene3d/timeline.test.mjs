// Python supplies real production timeline() output; no second authored timeline.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import { createTimeline, flight, flightHeight } from './timeline.mjs';

const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const data = cases.counted, track = createTimeline(data);
const at = (t) => track.sample(t * data.scale);
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);

test('the production beads keep all source events, groups and framework pulses', () => {
  assert.deepEqual(track.events, [...data.run1, ...data.run2.beads, ...data.pulses]);
  assert.equal(data.run1.length, 7);
  assert.deepEqual(data.run2.kind_order, ['state', 'tool', 'text']);
  assert.deepEqual(data.run2.tallies.map((row) => row.total), [35, 18, 22]);
  assert.equal(data.run2.beads.length, 77);
  assert.equal(data.run2.beads[0].kind, 'life');
  assert.equal(data.run2.beads.at(-1).kind, 'life');
  for (const event of track.events) {
    const index = track.events.indexOf(event);
    assert.ok(at((event.t0 + event.t1) / 2).flights[index].opacity > .99);
    assert.equal(at(event.t0 - .1).flights[index].opacity, 0);
    assert.equal(at(event.t1 + .2).flights[index].opacity, 0);
  }
});

test('request rises and events fall through an eased protocol keyframe', () => {
  const request = data.request, event = data.run1[0];
  const r0 = flightHeight(1 - at(request.t0).request.progress);
  const r1 = flightHeight(1 - at(request.t1).request.progress);
  assert.ok(r0 < r1);
  near(flightHeight(flight((event.t0 + event.t1) / 2, event).progress), .14);
  assert.ok(flightHeight(flight(event.t0, event).progress) > flightHeight(flight(event.t1, event).progress));
  let previous = -1;
  for (let i = 0; i <= 100; i++) {
    const p = flight(event.t0 + (event.t1 - event.t0) * i / 100, event).progress;
    assert.ok(p >= previous && p <= 1); previous = p;
  }
});

test('the app appends exactly the three arrived deltas and closes on message end', () => {
  let text = '';
  for (const event of data.run1.filter((event) => event.delta != null)) {
    assert.equal(at(event.t1 - .0001).response, text);
    text += event.delta;
    assert.equal(at(event.t1 + .0001).response, text);
    assert.ok(at(event.t1 + .0001).open);
  }
  assert.equal(text, 'Hello from AG-UI!');
  const end = data.run1.find((event) => event.name === 'TEXT_MESSAGE_END').t1;
  assert.equal(at(end + .0001).open, false);
  assert.equal(at(data.run1.at(-1).t1 + .001).status, 'Hoàn tất');
});

test('every demo landing increments only its tally and snapshots update app state', () => {
  const expected = [0, 0, 0];
  for (const bead of data.run2.beads) {
    assert.deepEqual(at(bead.t1 - .00001).tallies, expected);
    const index = data.run2.kind_order.indexOf(bead.kind);
    if (index >= 0) expected[index]++;
    assert.deepEqual(at(bead.t1 + .00001).tallies, expected);
    if (bead.kind === 'state') {
      const sample = at(bead.t1 + .00001);
      near(sample.state.fraction, expected[0] / 35);
      assert.ok(sample.state.note);
      assert.ok(at(bead.t1 + .06).state.hot > .99);
    }
  }
  assert.deepEqual(expected, [35, 18, 22]);
  near(at(20.3).textFraction, 1);
  assert.equal(at(15).state.note, false);
});

test('names-only runs have three representative beads and never invent totals', () => {
  const names = createTimeline(cases.names);
  assert.deepEqual(names.sample(cases.names.duration * .78).tallies, [null, null, null]);
  assert.equal(cases.names.run2.beads.length, 5);
});

test('all framework changes reset their tile turns on reverse seeks', () => {
  data.swap.forEach((item, index) => {
    const s = at(item.a + .7);
    assert.equal(s.framework, index);
    s.tiles.forEach((turn) => near(turn, index * Math.PI));
  });
  assert.deepEqual(at(2).tiles, Array(12).fill(0));
  near(track.activity(data.swap.at(-1).a + .625, 1), 1);
});

test('forward, reverse and shuffled samples agree at every frame, without mutating inputs', () => {
  for (const d of Object.values(cases)) {
    const before = JSON.stringify(d), timeline = createTimeline(d);
    const samples = Array.from({ length: d.frames }, (_, i) => JSON.stringify(timeline.sample(i / d.fps)));
    for (let i = d.frames - 1; i >= 0; i--) assert.equal(JSON.stringify(timeline.sample(i / d.fps)), samples[i]);
    for (let n = 0; n < d.frames; n++) {
      const i = (n * 137) % d.frames;
      assert.equal(JSON.stringify(timeline.sample(i / d.fps)), samples[i]);
    }
    assert.equal(JSON.stringify(d), before);
    assert.deepEqual(timeline.sample(-1), timeline.sample(0));
    assert.deepEqual(timeline.sample(d.duration + 5), timeline.sample(d.duration));
    for (const bad of [NaN, Infinity, -Infinity, '2', null]) assert.throws(() => timeline.sample(bad), TypeError);
  }
});

test('duration scales all five acts and flights without changing their authored time', () => {
  for (const d of Object.values(cases)) {
    const timeline = createTimeline(d);
    for (const act of d.acts) assert.equal(timeline.sample((act.a + .01) * d.scale).act, act.name);
    near(timeline.sample(d.duration).t, d.base);
  }
});

test('the narrated clip repeats exact frame times through the last README event', () => {
  const d = cases.narrated, timeline = createTimeline(d);
  assert.equal(d.duration, 25); assert.equal(d.frames, 750); assert.equal(d.fps, 30);
  const last = d.run1.at(-1), firstLanding = Math.ceil(last.t1 * d.scale * d.fps);
  const samples = Array.from({ length: d.frames }, (_, frame) => timeline.sample(frame / d.fps));
  assert.equal(samples[412].currentEvent, 6);
  assert.equal(samples[412].status, 'Đã nhận xong');
  assert.equal(samples[412].response, 'Hello from AG-UI!');
  assert.equal(samples[412].open, false);
  assert.ok(samples[412].flights[6].progress < 1);
  assert.equal(samples[firstLanding - 1].status, 'Đã nhận xong');
  assert.equal(samples[firstLanding].status, 'Hoàn tất');
  for (const previous of [749, 127, 0, firstLanding]) {
    timeline.sample(previous / d.fps);
    for (let frame = firstLanding + 2; frame >= 410; frame--) {
      assert.deepEqual(timeline.sample(frame / d.fps), samples[frame]);
      // Also sample the illuminated node lattice, outside the UI sampler.
      for (let layer = 0; layer < 3; layer++) {
        const t = samples[frame].t;
        assert.equal(timeline.activity(t, layer, 2.4, 3.1), createTimeline(d).activity(t, layer, 2.4, 3.1));
      }
    }
  }
});

test('fractional narration and the render matrix retain smooth lattice activity around the last arrival', () => {
  assert.equal(cases.voiced.duration, 25.25);
  assert.equal(cases.voiced.frames, 758);
  const voiced = createTimeline(cases.voiced).sample(416 / 30);
  assert.equal(voiced.currentEvent, 6);
  assert.equal(voiced.status, 'Đã nhận xong');
  for (const d of Object.values(cases)) {
    const timeline = createTimeline(d), landing = d.run1.at(-1).t1;
    const frame = Math.ceil(landing * d.scale * d.fps);
    for (let f = frame - 12; f <= frame + 12; f++) {
      const seconds = f / d.fps, t = timeline.sample(seconds).t;
      // Sample every real node, including the bright wave front, on both sides
      // of sub-frame time offsets. Arrival labels/counts may step; light must not.
      for (let layer = 0; layer < 3; layer++) for (let x = 0; x < 9; x++) for (let z = 0; z < 6; z++) {
        const px = (x - 4) * .66, pz = (z - 2.5) * .59;
        const radius = Math.hypot(px - 1.1, pz - .5), requestRadius = Math.hypot(px + 1.25, pz - .6);
        const activity = timeline.activity(t, layer, radius, requestRadius);
        assert.ok(Number.isFinite(activity) && activity >= 0 && activity <= 1);
        assert.ok(Math.abs(activity - timeline.activity(t + .00001, layer, radius, requestRadius)) < .0001);
        timeline.sample(d.duration);
        assert.equal(timeline.activity(timeline.sample(seconds).t, layer, radius, requestRadius), activity);
      }
    }
  }
});
