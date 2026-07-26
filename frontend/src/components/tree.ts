import type { BuildComponent, SerialTree } from "../api/types";

// Aggregate problem counts for a node *and everything below it*, so a collapsed
// parent can still make problems obvious at a glance.
export interface Flags {
  failed: number; // lots that failed incoming inspection
  openNC: number; // open nonconformances (on lots or on serials)
}

export function lotFailed(lot: NonNullable<BuildComponent["lot"]>): boolean {
  return lot.inspection_disposition === "rejected";
}

export function lotOpenNC(lot: NonNullable<BuildComponent["lot"]>): boolean {
  return lot.nonconformances.some((nc) => nc.status === "open");
}

export function lotNoCoC(lot: NonNullable<BuildComponent["lot"]>): boolean {
  return lot.certificate_status !== "present";
}

const cache = new WeakMap<SerialTree, Flags>();

// Total problems in a node's subtree (self + descendants).
export function subtreeFlags(node: SerialTree): Flags {
  const hit = cache.get(node);
  if (hit) return hit;
  let failed = 0;
  let openNC = node.nonconformances.filter((nc) => nc.status === "open").length;
  for (const comp of node.components) {
    if (comp.kind === "lot" && comp.lot) {
      if (lotFailed(comp.lot)) failed += 1;
      if (lotOpenNC(comp.lot)) openNC += 1;
    } else if (comp.kind === "serial" && comp.child) {
      const f = subtreeFlags(comp.child);
      failed += f.failed;
      openNC += f.openNC;
    }
  }
  const flags = { failed, openNC };
  cache.set(node, flags);
  return flags;
}

export function hasIssues(f: Flags): boolean {
  return f.failed > 0 || f.openNC > 0;
}

// ---- Row flattening (respecting expand state) ---------------------------- //

export type Row =
  | { type: "unit"; key: string; depth: number; position: string | null; node: SerialTree; flags: Flags; expandable: boolean }
  | { type: "lot"; key: string; depth: number; position: string | null; comp: BuildComponent }
  | { type: "orphan"; key: string; depth: number; position: string | null; comp: BuildComponent };

function childKey(path: string, comp: BuildComponent, i: number): string {
  return `${path}/${comp.position ?? `#${i}`}`;
}

export function flatten(root: SerialTree, expanded: Set<string>): Row[] {
  const rows: Row[] = [];
  const walk = (node: SerialTree, depth: number, position: string | null, path: string) => {
    rows.push({
      type: "unit",
      key: path,
      depth,
      position,
      node,
      flags: subtreeFlags(node),
      expandable: node.components.length > 0,
    });
    if (!expanded.has(path)) return;
    node.components.forEach((comp, i) => {
      const key = childKey(path, comp, i);
      if (comp.kind === "serial" && comp.child) {
        walk(comp.child, depth + 1, comp.position, key);
      } else {
        rows.push({ type: comp.kind === "lot" ? "lot" : "orphan", key, depth: depth + 1, position: comp.position, comp });
      }
    });
  };
  walk(root, 0, null, root.serial_number ?? "root");
  return rows;
}

// Every unit path, for "expand all".
export function allUnitKeys(root: SerialTree): string[] {
  const keys: string[] = [];
  const walk = (node: SerialTree, path: string) => {
    keys.push(path);
    node.components.forEach((comp, i) => {
      if (comp.kind === "serial" && comp.child) walk(comp.child, childKey(path, comp, i));
    });
  };
  walk(root, root.serial_number ?? "root");
  return keys;
}
