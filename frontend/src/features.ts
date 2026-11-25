import { createContext, useContext } from "react";

// Feature switches served by the backend (/api/me -> features, config.yaml -> features).
// Media Compliance is hidden for now; its pages and code stay in the codebase.
export type Features = { media_compliance: boolean };

export const DEFAULT_FEATURES: Features = { media_compliance: false };

export const FeaturesContext = createContext<Features>(DEFAULT_FEATURES);

export const useFeatures = () => useContext(FeaturesContext);
