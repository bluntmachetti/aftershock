// Resource-kind short codes — mirrors ResourceKind in src/aftershock/town/state.py
// and the prototype's RES dict. The contention overlay labels a contested link
// with the resource's short code (e.g. "RPR CONTESTED").

export const RESOURCE_CODES: Record<string, string> = {
  ambulance: 'AMB',
  rescue_crew: 'RSC',
  fire_engine: 'ENG',
  repair_crew: 'RPR',
  supply_truck: 'SUP',
}

/** Short code for a resource kind; falls back to the first three letters
 *  upper-cased for an unknown kind (never throws). */
export function resourceCode(kind: string): string {
  return RESOURCE_CODES[kind] ?? kind.slice(0, 3).toUpperCase()
}
