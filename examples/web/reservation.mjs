// Self-created P03 fixture: reservation workflow with real HTTP and error states.
// This is inspectable teaching material, not a hidden P04 benchmark or oracle.
export function createService() {
  let available = 7;
  let nextId = 1;
  const reservations = new Map();
  return {
    snapshot() {
      return {available, reservations: [...reservations.values()].map(value => ({...value}))};
    },
    async handle({method, path, body}) {
      if (method === 'POST' && path === '/reservations') {
        if (body?.item !== 'widget' || !Number.isInteger(body?.quantity) || body.quantity <= 0)
          return {status: 400, body: {error: 'invalid-reservation'}};
        if (body.quantity > available) return {status: 409, body: {error: 'insufficient-stock'}};
        const reservation = {id: `reservation-${nextId++}`, quantity: body.quantity, status: 'reserved'};
        available -= reservation.quantity;
        reservations.set(reservation.id, reservation);
        return {status: 201, body: {...reservation}};
      }
      const match = /^\/reservations\/(reservation-[0-9]+)\/commit$/.exec(path);
      if (method === 'POST' && match) {
        const reservation = reservations.get(match[1]);
        if (!reservation) return {status: 404, body: {error: 'reservation-not-found'}};
        if (reservation.status !== 'reserved') return {status: 409, body: {error: 'already-committed'}};
        reservation.status = 'committed';
        return {status: 200, body: {...reservation}};
      }
      return {status: 404, body: {error: 'route-not-found'}};
    },
  };
}

export function createSession({request}) {
  let state = {phase: 'idle', reservation: null, lastError: null};
  return {
    snapshot() {return structuredClone(state);},
    async dispatch(action) {
      if (action.type === 'reserve') {
        if (state.phase !== 'idle') throw new Error('reservation-already-open');
        const response = await request('POST', '/reservations', {item: 'widget', quantity: action.quantity});
        if (response.status !== 201) {
          state.lastError = response.body.error;
          return {accepted: false, error: response.body.error};
        }
        state = {phase: 'reserved', reservation: response.body, lastError: null};
        return {accepted: true, reservationId: response.body.id};
      }
      if (action.type === 'commit') {
        if (state.phase !== 'reserved') throw new Error('no-reservation-to-commit');
        const response = await request('POST', `/reservations/${state.reservation.id}/commit`);
        if (response.status !== 200) throw new Error(response.body.error);
        state = {phase: 'committed', reservation: response.body, lastError: null};
        return {committed: true};
      }
      throw new Error('unknown-interaction');
    },
  };
}
