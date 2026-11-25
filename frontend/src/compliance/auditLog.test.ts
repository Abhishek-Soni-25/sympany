import { describe, it, expect } from "vitest";
import { pseudonymise, buildAuditRecord, withOverride, toCsv } from "./auditLog";
import type { ExtractedAsset, Verdict } from "./types";

const asset: ExtractedAsset = {
  assetId: "a1",
  adviserId: "ADV-99",
  channel: "instagram",
  imageText: [{ text: "Insured person 756.1234.5678.97 Policy Number: 88123456 Deductible 2500" }],
  transcript: "My AHV number is 756.1234.5678.97",
  captionText: "Hospital supplementary insurance",
  frames: ["data:image/jpeg;base64,AAAA"],
  extractionStatus: "complete",
};

const verdict: Verdict = {
  outcome: "REJECT",
  activeHits: [
    {
      ruleId: "D-01", title: "Customer policy or benefit statement visible", severity: "High", status: "active",
      type: "prohibition", confidence: 0.92, region: { kind: "image", snippet: "Policy Number: 88123456" },
      basis: "Swiss FADP", reviewerNote: "note", suggestedFix: "fix", belowFloor: false,
    },
  ],
  advisoryHits: [],
  notEvaluated: [],
  reasons: [{ code: "high_severity_breach", message: "x" }],
  requiresManualReview: false,
  ruleSetVersion: "1.0.0",
};

describe("pseudonymise", () => {
  it("masks AHV/AVS numbers", () => {
    const out = pseudonymise("Customer 756.1234.5678.97 signed up");
    expect(out).not.toContain("756.1234.5678.97");
    expect(out).toMatch(/\[AHV:[0-9a-f]{8}\]/);
  });

  it("is deterministic — same value maps to the same token", () => {
    expect(pseudonymise("756.1234.5678.97")).toBe(pseudonymise("756.1234.5678.97"));
  });

  it("masks long policy/account numbers", () => {
    const out = pseudonymise("Policy Number: 88123456");
    expect(out).not.toContain("88123456");
  });
});

describe("buildAuditRecord", () => {
  it("pseudonymises extracted text and transcript before storing", () => {
    const rec = buildAuditRecord({ asset, verdict, submittedAt: "2026-07-16T00:00:00Z" });
    expect(rec.extractedText).not.toContain("756.1234.5678.97");
    expect(rec.extractedText).not.toContain("88123456");
    expect(rec.transcript).not.toContain("756.1234.5678.97");
    expect(rec.assetHash).toMatch(/^sha_/);
    expect(rec.computedOutcome).toBe("REJECT");
    expect(rec.finalDisposition).toBe("REJECT");
    expect(rec.ruleSetVersion).toBe("1.0.0");
  });

  it("does not carry a raw AHV number on an evidence snippet", () => {
    const withAhv: Verdict = {
      ...verdict,
      activeHits: [{ ...verdict.activeHits[0], region: { kind: "image", snippet: "AHV 756.1234.5678.97" } }],
    };
    const rec = buildAuditRecord({ asset, verdict: withAhv, submittedAt: "t" });
    expect(JSON.stringify(rec.hits)).not.toContain("756.1234.5678.97");
  });
});

describe("withOverride", () => {
  it("requires a justification", () => {
    const rec = buildAuditRecord({ asset, verdict, submittedAt: "t" });
    expect(() => withOverride(rec, { officerId: "O1", justification: "  ", outcome: "APPROVE", at: "t2" })).toThrow();
  });

  it("records the override and updates final disposition without mutating the original", () => {
    const rec = buildAuditRecord({ asset, verdict, submittedAt: "t" });
    const overridden = withOverride(rec, { officerId: "O1", justification: "False positive, sample doc", outcome: "APPROVE", at: "t2" });
    expect(overridden.finalDisposition).toBe("APPROVE");
    expect(overridden.override?.officerId).toBe("O1");
    expect(overridden.computedOutcome).toBe("REJECT"); // original computed outcome preserved
    expect(rec.override).toBeNull(); // append-only: original untouched
  });
});

describe("toCsv", () => {
  it("emits a header plus one row per record and escapes quotes", () => {
    const rec = buildAuditRecord({ asset, verdict, submittedAt: "t" });
    const csv = toCsv([rec]);
    const lines = csv.split("\r\n");
    expect(lines[0]).toContain("assetHash");
    expect(lines).toHaveLength(2);
    expect(csv).toContain("REJECT");
  });

  it("handles an empty log (header only)", () => {
    expect(toCsv([]).split("\r\n")).toHaveLength(1);
  });
});
