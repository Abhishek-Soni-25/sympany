import { describe, it, expect } from "vitest";
import { matchRules } from "./ruleMatcher";
import { DEFAULT_RULE_SET } from "./rules";
import type { ExtractedAsset, RuleSet } from "./types";

function asset(over: Partial<ExtractedAsset>): ExtractedAsset {
  return {
    assetId: "a1",
    adviserId: "adv1",
    channel: "instagram",
    imageText: [],
    transcript: "",
    captionText: "",
    frames: [],
    extractionStatus: "complete",
    metadata: { date: "2026-07-16", version: "1" },
    ...over,
  };
}

describe("ruleMatcher against the shipped rule set", () => {
  it("D-04: fires on a guaranteed-premiums lexicon match (High/active)", () => {
    const { hits } = matchRules(asset({ captionText: "Our new hospital cover comes with guaranteed premiums for life." }), DEFAULT_RULE_SET);
    const d04 = hits.find((h) => h.ruleId === "D-04");
    expect(d04).toBeTruthy();
    expect(d04!.severity).toBe("High");
    expect(d04!.status).toBe("active");
  });

  it("D-03: fires when a percentage sits alongside a premium-saving term", () => {
    const { hits } = matchRules(asset({ captionText: "Switch to the Telmed model and save up to 25% on your premium." }), DEFAULT_RULE_SET);
    expect(hits.some((h) => h.ruleId === "D-03")).toBe(true);
  });

  it("D-03: does NOT fire on a percentage with no saving context", () => {
    const { hits } = matchRules(asset({ captionText: "80% of Swiss residents want peace of mind." }), DEFAULT_RULE_SET);
    expect(hits.some((h) => h.ruleId === "D-03")).toBe(false);
  });

  it("D-01: fires when two or more policy / benefit statement field labels appear in one frame", () => {
    const { hits } = matchRules(
      asset({ imageText: [{ text: "Policy Number: 123  Deductible: CHF 2,500  Monthly Premium: CHF 412.80", frame: 0 }], frames: ["data:img"] }),
      DEFAULT_RULE_SET,
    );
    expect(hits.some((h) => h.ruleId === "D-01")).toBe(true);
  });

  it("D-01: does NOT fire on a single field label", () => {
    const { hits } = matchRules(asset({ imageText: [{ text: "Insurance Model: Telmed", frame: 0 }], frames: ["x"] }), DEFAULT_RULE_SET);
    expect(hits.some((h) => h.ruleId === "D-01")).toBe(false);
  });

  it("D-02: fires on an AHV number in a product context", () => {
    const { hits } = matchRules(asset({ captionText: "Congrats to policyholder 756.1234.5678.97 on your new hospital insurance!" }), DEFAULT_RULE_SET);
    expect(hits.some((h) => h.ruleId === "D-02")).toBe(true);
  });

  it("A-01/A-02/A-03: are NOT evaluated while phrase lists are empty (day-one behaviour)", () => {
    const { hits, notEvaluated } = matchRules(asset({ captionText: "Check out our new supplementary insurance for dental care." }), DEFAULT_RULE_SET);
    for (const id of ["A-01", "A-02", "A-03"]) {
      expect(hits.some((h) => h.ruleId === id)).toBe(false);
      const ne = notEvaluated.find((n) => n.ruleId === id);
      expect(ne).toBeTruthy();
      expect(ne!.reason).toBe("awaiting approved phrase list");
    }
  });

  it("A-01: evaluates and fires once its phrase list is populated but the phrase is absent", () => {
    const populated: RuleSet = {
      ...DEFAULT_RULE_SET,
      phraseLists: { ...DEFAULT_RULE_SET.phraseLists, riskWarning: ["Supplementary insurance is subject to a health declaration"] },
    };
    const { hits, notEvaluated } = matchRules(asset({ captionText: "Check out our new supplementary insurance for dental care." }), populated);
    expect(hits.some((h) => h.ruleId === "A-01")).toBe(true);
    expect(notEvaluated.some((n) => n.ruleId === "A-01")).toBe(false);
  });

  it("A-01: does NOT fire when the approved risk warning is present", () => {
    const populated: RuleSet = {
      ...DEFAULT_RULE_SET,
      phraseLists: { ...DEFAULT_RULE_SET.phraseLists, riskWarning: ["health declaration"] },
    };
    const { hits } = matchRules(asset({ captionText: "Hospital insurance from Sympany. Acceptance is subject to a health declaration." }), populated);
    expect(hits.some((h) => h.ruleId === "A-01")).toBe(false);
  });

  it("A-04: fires when register metadata (date/version) is missing", () => {
    const { hits } = matchRules(asset({ metadata: {} }), DEFAULT_RULE_SET);
    const a04 = hits.find((h) => h.ruleId === "A-04");
    expect(a04).toBeTruthy();
    expect(a04!.severity).toBe("Low");
  });

  it("pending_config rules never produce hits and are all reported as not evaluated", () => {
    const { hits, notEvaluated } = matchRules(asset({ captionText: "join our broker team, earn CHF 10,000 a month #hashtag" }), DEFAULT_RULE_SET);
    const pending = ["D-09", "D-11", "D-12", "A-07", "A-08", "A-09", "A-10", "A-11", "A-12"];
    for (const id of pending) {
      expect(hits.some((h) => h.ruleId === id)).toBe(false);
      expect(notEvaluated.some((n) => n.ruleId === id && n.reason === "pending configuration")).toBe(true);
    }
  });

  it("a clean asset produces no hits", () => {
    const { hits } = matchRules(asset({ captionText: "Wishing everyone a happy Swiss National Day from our team in Basel." }), DEFAULT_RULE_SET);
    expect(hits).toHaveLength(0);
  });
});
