interface DealConfirmationOptions<T> {
  seller: boolean;
  gameId?: string | null;
  submit(): Promise<T>;
  copyId(value: string, container: HTMLElement): Promise<boolean>;
  haptic(kind: "open" | "success" | "error"): void;
}
interface Window {
  AutoFlowDealConfirmation: {
    confirm<T>(options: DealConfirmationOptions<T>): Promise<T | null>;
    dismiss(): boolean;
  };
}
