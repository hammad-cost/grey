/**
 * The proposal as the frontend receives it (Release 0.14).
 * The backend sends it inside event data as `proposal`. Read safely.
 */

export type ProposalSection = {
  id: string;
  title: string;
  paragraphs: string[];
  items: string[];
  sources: string[];
  written_by: string;     // "grey" (built from approved decisions) | "model"
};
export type ProposalReference = {
  number: number;
  title: string;
  organization: string;
  url: string;
  published: string | null;
  source_type: string;
};
export type Proposal = { title: string; sections: ProposalSection[]; references: ProposalReference[] };
export type StoredProposal = { id: string; status: "draft" | "final"; proposal: Proposal; rewrites_used: number };
export type ProposalView = {
  fyp_title: string;
  proposal: StoredProposal | null;
  rewrites_left: number;
  max_rewrites: number;
  rewritable_sections: string[];
};

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(isText) : [];
}

function readSection(value: unknown): ProposalSection | null {
  const s = value as ProposalSection;
  if (!s || !isText(s.id) || !isText(s.title)) return null;
  return {
    id: s.id, title: s.title, paragraphs: texts(s.paragraphs), items: texts(s.items),
    sources: texts(s.sources), written_by: isText(s.written_by) ? s.written_by : "grey",
  };
}

function readReference(value: unknown): ProposalReference | null {
  const r = value as ProposalReference;
  if (!r || typeof r.number !== "number" || !isText(r.title) || !isText(r.url) || !/^https?:\/\//.test(r.url)) return null;
  return {
    number: r.number, title: r.title, organization: isText(r.organization) ? r.organization : "", url: r.url,
    published: isText(r.published) ? r.published : null, source_type: isText(r.source_type) ? r.source_type : "",
  };
}

/** The proposal view from an event's data, or null if it isn't there. */
export function readProposal(eventData?: Record<string, unknown>): ProposalView | null {
  const v = eventData?.proposal as ProposalView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  const s = v.proposal as StoredProposal | null;
  const p = s?.proposal;
  const proposal = s && isText(s.id) && p && isText(p.title)
    ? {
        id: s.id,
        status: s.status === "final" ? "final" as const : "draft" as const,
        proposal: {
          title: p.title,
          sections: (Array.isArray(p.sections) ? p.sections.map(readSection) : []).filter((x): x is ProposalSection => x !== null),
          references: (Array.isArray(p.references) ? p.references.map(readReference) : []).filter((x): x is ProposalReference => x !== null),
        },
        rewrites_used: typeof s.rewrites_used === "number" ? s.rewrites_used : 0,
      }
    : null;
  return {
    fyp_title: v.fyp_title,
    proposal,
    rewrites_left: typeof v.rewrites_left === "number" ? v.rewrites_left : 0,
    max_rewrites: typeof v.max_rewrites === "number" ? v.max_rewrites : 3,
    rewritable_sections: texts(v.rewritable_sections),
  };
}
