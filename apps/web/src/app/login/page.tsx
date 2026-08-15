"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAppStore } from "@/stores/app";
import { resetClient, EmeraldClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/typography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Brain, Loader, CheckCircle2, XCircle, Eye, EyeOff, ArrowRight,
} from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const {
    apiKey, baseUrl, entityId,
    setApiKey, setBaseUrl, setEntityId, setConnected, setDemoMode,
  } = useAppStore();

  const [localKey, setLocalKey] = useState(apiKey);
  const [localUrl, setLocalUrl] = useState(baseUrl);  // H1: 空 = 同源（经 nginx 代理），无需填写
  const [localEntity, setLocalEntity] = useState(entityId);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(null);
  const [testMessage, setTestMessage] = useState("");

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    setTestMessage("");
    try {
      resetClient();
      const client = new EmeraldClient(
        { apiKey: localKey, baseUrl: localUrl, entityId: localEntity },
        5_000
      );
      const health = await client.health();
      setTestResult("success");
      setTestMessage(`Connected — ${health.version ?? "v0.1.0"}`);
    } catch (err) {
      setTestResult("error");
      setTestMessage(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setTesting(false);
    }
  };

  const handleConnect = () => {
    setApiKey(localKey);
    setBaseUrl(localUrl);
    setEntityId(localEntity);
    setDemoMode(false);
    setConnected(true);
    resetClient();
    router.push("/");
  };

  const handleDemo = () => {
    setDemoMode(true);
    setConnected(true);
    router.push("/");
  };

  const isValid = localKey.trim() && localEntity.trim();  // URL 可空 = 同源

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface-base p-4">
      {/* Logo */}
      <div className="mb-8 flex items-center gap-3">
        <Brain className="h-8 w-8 text-brand-accent" />
        <span className="text-2xl font-bold tracking-tight text-fg-primary">
          Emerald
        </span>
      </div>

      <Card className="w-full max-w-md">
        <CardHeader className="text-center pb-2">
          <CardTitle className="text-lg text-fg-primary">Connect to Emerald</CardTitle>
          <p className="text-sm text-fg-muted mt-1">
            Enter your Emerald server details to continue
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Server URL */}
          <div className="space-y-1.5">
            <Label level="3" weight="medium" className="text-fg-faint">
              Server URL
            </Label>
            <Input
              value={localUrl}
              onChange={(e) => setLocalUrl(e.target.value)}
              placeholder="Leave empty for same origin"
            />
          </div>

          {/* API Key */}
          <div className="space-y-1.5">
            <Label level="3" weight="medium" className="text-fg-faint">
              API Key
            </Label>
            <div className="relative">
              <Input
                value={localKey}
                onChange={(e) => setLocalKey(e.target.value)}
                type={showKey ? "text" : "password"}
                placeholder="sk-..."
                className="pr-9"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-primary"
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Entity ID */}
          <div className="space-y-1.5">
            <Label level="3" weight="medium" className="text-fg-faint">
              Entity ID
            </Label>
            <Input
              value={localEntity}
              onChange={(e) => setLocalEntity(e.target.value)}
              placeholder="user_123"
            />
          </div>

          {/* Test connection */}
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleTest}
              disabled={testing || !isValid}
              className="flex-1"
            >
              {testing ? (
                <Loader className="h-4 w-4 animate-spin mr-1.5" />
              ) : null}
              Test Connection
            </Button>
            <Button
              onClick={handleConnect}
              disabled={!isValid}
              className="flex-1"
            >
              Connect
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Button>
          </div>

          {/* Test result */}
          {testResult && (
            <div
              className={`flex items-start gap-2 rounded-lg p-3 text-sm ${
                testResult === "success"
                  ? "bg-bg-success/30 text-text-success"
                  : "bg-bg-error/30 text-text-error"
              }`}
            >
              {testResult === "success" ? (
                <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 mt-0.5 shrink-0" />
              )}
              <span>{testMessage}</span>
            </div>
          )}

          {/* Divider */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-surface-border" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-surface-card px-2 text-fg-faint">or</span>
            </div>
          </div>

          {/* Demo mode */}
          <Button variant="ghost" onClick={handleDemo} className="w-full">
            Continue with Demo Mode
          </Button>
        </CardContent>
      </Card>

      <p className="mt-6 text-xs text-fg-faint">
        Need help?{" "}
        <Link href="/settings" className="text-brand-accent hover:underline">
          Configure later in Settings
        </Link>
      </p>
    </div>
  );
}
