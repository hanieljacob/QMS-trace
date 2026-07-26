import { createContext, useContext } from "react";

export type Route =
  | { kind: "home" }
  | { kind: "serial"; id: string }
  | { kind: "lot"; id: string };

export interface Nav {
  openSerial: (serialNumber: string) => void;
  openLot: (lotNumber: string) => void;
  back: () => void;
  canBack: boolean;
}

export const NavContext = createContext<Nav>({
  openSerial: () => {},
  openLot: () => {},
  back: () => {},
  canBack: false,
});

export const useNav = () => useContext(NavContext);
