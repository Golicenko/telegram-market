interface ReferralSummary {
  referralCode: string;
  referralUrl: string;
  referralCount: number;
  referralLimit: number;
  commissionPercent: number;
  canInvite: boolean;
  milestones: { count: number; reward: number; completed: boolean }[];
  shareText: string;
}
interface ReferralPageOptions {
  api: { request(path: string, options?: { method?: string; retries?: number; timeoutMs?: number }): Promise<any> };
  notify(message: string): void;
  refreshWallet(): Promise<void>;
}
interface Window {
  AutoFlowReferrals: { create(options: ReferralPageOptions): { setActive(active: boolean): void } };
  Telegram?: { WebApp?: {
    shareMessage?(id: string, callback: (sent: boolean) => void): void;
    isVersionAtLeast?(version: string): boolean;
    openTelegramLink?(url: string): void;
  } };
}
