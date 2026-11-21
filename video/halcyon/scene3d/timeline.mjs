// Frame-addressed choreography. All facts and authored times come from canh.py.
export const clamp = (x, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x));
export const mix = (a, b, u) => a + (b - a) * u;
export const unit = (t, a, b) => clamp((t - a) / (b - a));
export const smooth = (u) => u * u * (3 - 2 * u);
export const ease = (t, a, b) => smooth(unit(t, a, b));
export const envelope = (t, a, b, c, d) => ease(t, a, b) * (1 - ease(t, c, d));
export const pulse = (t, at, width = .18) => Math.exp(-(((t - at) / width) ** 2));

// Each half-flight has its own ease: the middle keyframe is the protocol plate.
export function progress(t, a, b) {
  const middle = (a + b) / 2;
  return t < middle ? .5 * ease(t, a, middle) : .5 + .5 * ease(t, middle, b);
}
export function flight(t, event) {
  return { progress: progress(t, event.t0, event.t1),
    opacity: envelope(t, event.t0 - .08, event.t0 + .08, event.t1, event.t1 + .16) };
}
export function flightHeight(p) {
  return p <= .5 ? mix(2.85, .14, p * 2) : mix(.14, -2.4, (p - .5) * 2);
}

export function createTimeline(data) {
  const acts = Object.fromEntries(data.acts.map((act) => [act.name, act]));
  const events = [...data.run1, ...data.run2.beads, ...data.pulses];
  const state = data.run2.beads.filter((event) => event.kind === 'state');
  const text = data.run2.beads.filter((event) => event.kind === 'text');
  const deltas = data.run1.filter((event) => event.delta != null);
  const count = (list, t) => list.filter((event) => event.t1 <= t).length;
  const firstMessage = data.run1.find((event) => event.name === 'TEXT_MESSAGE_START').t1;
  const endMessage = data.run1.find((event) => event.name === 'TEXT_MESSAGE_END').t1;
  const endRun = data.run1.at(-1).t1;
  function sample(value) {
    if (!Number.isFinite(value)) throw new TypeError('renderAt expects finite seconds');
    const t = clamp(value / data.scale, 0, data.base);
    const act = data.acts.findLast((item) => t >= item.a).name;
    const tools = envelope(t, acts.tools.a, acts.tools.a + .25, acts.tools.b - .25, acts.tools.b);
    const currentEvent = data.run1.findLastIndex((event) => t >= event.t0);
    const framework = Math.max(0, data.swap.findLastIndex((item) => t >= item.a));
    const stateFraction = state.length ? count(state, t) / state.length : 0;
    const textFraction = text.length ? count(text, t) / text.length : 0;
    const hot = Math.max(0, ...state.map((event) => pulse(t, event.t1 + .06, .14)));
    return { t, act, tools, framework, currentEvent,
      flights: events.map((event) => flight(t, event)),
      request: flight(t, data.request),
      response: deltas.filter((event) => event.t1 <= t).map((event) => event.delta).join(''),
      received: deltas.map((event) => ease(t, event.t1, event.t1 + .24)),
      open: t >= firstMessage && t < endMessage,
      status: t < data.run1[0].t1 ? 'Sẵn sàng' : t < firstMessage ? 'Đang chạy' : t < endMessage ? 'Đang nhận' : t < endRun ? 'Đã nhận xong' : 'Hoàn tất',
      tallies: data.run2.tallies.map((row) => row.total == null ? null : row.ticks.filter((at) => at <= t).length),
      state: { fraction: stateFraction, hot, note: state.length > 0 && t >= state[0].t1 && t <= state.at(-1).t1 + .8 },
      textFraction,
      toolHot: Math.max(0, ...data.run2.beads.filter((event) => event.kind === 'tool').map((event) => pulse(t, event.t0, .14))),
      connection: Math.max(0, ...data.runs.map((run) => envelope(t, run.a, run.a + .2, run.b, run.b + .3))),
      // Reset every tile, including pre-swap frames reached by a reverse seek.
      tiles: Array.from({ length: 12 }, (_, index) => data.swap.slice(1).reduce((turn, item) =>
        turn + Math.PI * ease(t, item.a + index * .012, item.a + .48 + index * .012), 0)),
    };
  }
  function activity(t, layer, radius = 0, requestRadius = radius) {
    const crossing = layer / 2;
    return Math.max(pulse(t, mix(data.request.t1, data.request.t0, crossing) + requestRadius * .07, .17),
      ...events.map((event) => pulse(t, mix(event.t0, event.t1, crossing) + radius * .07, .16)));
  }
  return { sample, activity, events };
}
