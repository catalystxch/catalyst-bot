import SignClient from "@walletconnect/sign-client";
import { getSdkError } from "@walletconnect/utils";
import QRCode from "qrcode";

const ALLOWED_METHOD = "chia_signMessageByAddress";

type SigningRequest = {
  request_id: string;
  method: string;
  required_methods: string[];
  account: string;
  chain: string;
  signing_address: string;
  message: string;
  message_digest: string;
  expires_at: string;
};

type SigningCallbacks = {
  onPairingUri?: (uri: string, qrDataUrl: string) => void;
  onState?: (state: string, detail?: string) => void;
};

type StartOptions = SigningCallbacks & {
  projectId: string;
  request: SigningRequest;
};

let activeClient: Awaited<ReturnType<typeof SignClient.init>> | null = null;
let activeTopic: string | null = null;

function assertSigningRequest(request: SigningRequest): void {
  if (
    !request ||
    request.method !== ALLOWED_METHOD ||
    request.required_methods.length !== 1 ||
    request.required_methods[0] !== ALLOWED_METHOD ||
    !request.account.startsWith(`${request.chain}:`) ||
    !request.message.startsWith("0x")
  ) {
    throw new Error("invalid_signing_request");
  }
}

async function disconnect(): Promise<void> {
  const client = activeClient;
  const topic = activeTopic;
  activeClient = null;
  activeTopic = null;
  if (client && topic) {
    await client
      .disconnect({ topic, reason: getSdkError("USER_DISCONNECTED") })
      .catch(() => undefined);
  }
}

async function sign(options: StartOptions): Promise<Record<string, string>> {
  if (!options.projectId) throw new Error("walletconnect_project_id_missing");
  assertSigningRequest(options.request);
  await disconnect();
  options.onState?.("initializing");
  const client = await SignClient.init({
    projectId: options.projectId,
    metadata: {
      name: "CATalyst",
      description: "Approve a non-financial Market Bootstrap message signature.",
      url: "https://catalystxch.com",
      icons: ["https://catalystxch.com/assets/bot_icon_new.png"],
    },
  });
  activeClient = client;
  client.on("session_delete", () => {
    activeTopic = null;
    options.onState?.("disconnected");
  });

  const { uri, approval } = await client.connect({
    requiredNamespaces: {
      chia: {
        methods: [ALLOWED_METHOD],
        chains: [options.request.chain],
        events: [],
      },
    },
  });
  if (!uri) throw new Error("walletconnect_pairing_uri_missing");
  const qrDataUrl = await QRCode.toDataURL(uri, {
    errorCorrectionLevel: "M",
    margin: 2,
    width: 320,
  });
  options.onPairingUri?.(uri, qrDataUrl);
  options.onState?.("awaiting_session_approval");

  try {
    const session = await approval();
    activeTopic = session.topic;
    const namespace = session.namespaces.chia;
    const methods = namespace?.methods ?? [];
    const accounts = namespace?.accounts ?? [];
    if (
      methods.length !== 1 ||
      methods[0] !== ALLOWED_METHOD ||
      accounts.length !== 1 ||
      accounts[0] !== options.request.account
    ) {
      throw new Error("walletconnect_session_scope_mismatch");
    }
    options.onState?.("awaiting_message_approval");
    const result = await client.request<{ publicKey: string; signature: string }>({
      topic: session.topic,
      chainId: options.request.chain,
      request: {
        method: ALLOWED_METHOD,
        params: {
          address: options.request.signing_address,
          message: options.request.message,
        },
      },
    });
    options.onState?.("approved");
    return {
      requestId: options.request.request_id,
      account: options.request.account,
      address: options.request.signing_address,
      messageDigest: options.request.message_digest,
      publicKey: result.publicKey,
      signature: result.signature,
    };
  } finally {
    await disconnect();
  }
}

const api = Object.freeze({ sign, disconnect, allowedMethod: ALLOWED_METHOD });

declare global {
  interface Window {
    CatalystWalletConnectSigning: typeof api;
  }
}

window.CatalystWalletConnectSigning = api;
