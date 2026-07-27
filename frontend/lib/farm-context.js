"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { demoProvenance, isSecondaryDemoFarm } from "@/lib/farms";

// Active-farm context for the farm-scoped sidebar pages (Operations, Decisions,
// Scouting, Applications, Evidence). Farms come from the real, urgency-ranked
// /farms-overview list; the default active farm is the top-ranked visible one.
// The choice persists in localStorage (read only after mount — SSR-safe).

const STORAGE_KEY = "lumos.activeFarmId";

const FarmContext = createContext({
  farms: [],
  loading: true,
  error: null,
  activeFarm: null,
  setActiveFarmId: () => {},
  refresh: () => {},
});

export function FarmProvider({ children }) {
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeFarmId, setActiveFarmIdState] = useState(null);

  const refresh = useCallback(() => {
    return api
      .listFarmsOverview()
      .then((all) => {
        setFarms(all.filter((f) => !isSecondaryDemoFarm(f)));
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let stored = null;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      /* storage unavailable — fall through to the default */
    }
    if (stored) setActiveFarmIdState(Number(stored));
    refresh();
  }, [refresh]);

  const setActiveFarmId = useCallback((id) => {
    setActiveFarmIdState(id == null ? null : Number(id));
    try {
      if (id == null) window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
      /* non-fatal */
    }
  }, []);

  const activeFarm =
    farms.find((f) => f.id === activeFarmId) || (farms.length ? farms[0] : null);

  return (
    <FarmContext.Provider
      value={{ farms, loading, error, activeFarm, setActiveFarmId, refresh }}
    >
      {children}
    </FarmContext.Provider>
  );
}

export function useFarmContext() {
  return useContext(FarmContext);
}

// Demo-provenance tag for records the user creates on this farm (see
// lib/farms.demoProvenance). Secondary demo farms are filtered out of the
// context's farm list, so a form on one of them returns {} and the backend's
// mixing guard answers with its explanatory 409 instead.
export function useDemoTag(farmId) {
  return demoProvenance(useFarm(farmId));
}

// The farm record itself, when the caller needs a field off it (e.g. crop_type to
// resolve a pesticide label). Returns undefined until the provider has loaded.
export function useFarm(farmId) {
  const { farms } = useFarmContext();
  return farms.find((f) => f.id === Number(farmId));
}
