import { randomUUID } from "node:crypto";
import { GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

type UploadConfig = {
  region: string;
  bucket: string;
  accessKeyId?: string;
  secretAccessKey?: string;
};

export type UploadConfigStatus =
  | {
      configured: true;
      config: UploadConfig;
    }
  | {
      configured: false;
      missing: string[];
    };

export type CreateUploadPlanInput = {
  caseId: string;
  fileName: string;
  mimeType: string;
};

export type CreateUploadPlanResult = {
  s3Key: string;
  uploadUrl: string;
  expiresInSeconds: number;
};

export type CreateDownloadPlanInput = {
  s3Key: string;
  fileName?: string | null;
  disposition?: "inline" | "attachment";
};

export type CreateDownloadPlanResult = {
  downloadUrl: string;
  expiresInSeconds: number;
};

const PRESIGNED_URL_TTL_SECONDS = 15 * 60;
const PRESIGNED_DOWNLOAD_TTL_SECONDS = 10 * 60;
let cachedS3Client: S3Client | null = null;
let cachedS3ClientKey = "";

function readEnv(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value && value.length > 0 ? value : undefined;
}

function buildS3ClientCacheKey(config: UploadConfig): string {
  return [config.region, config.accessKeyId ?? "", config.secretAccessKey ?? ""].join("|");
}

function getS3Client(config: UploadConfig): S3Client {
  const cacheKey = buildS3ClientCacheKey(config);
  if (cachedS3Client && cacheKey === cachedS3ClientKey) {
    return cachedS3Client;
  }

  cachedS3Client = new S3Client({
    region: config.region,
    credentials:
      config.accessKeyId && config.secretAccessKey
        ? {
            accessKeyId: config.accessKeyId,
            secretAccessKey: config.secretAccessKey
          }
        : undefined
  });
  cachedS3ClientKey = cacheKey;

  return cachedS3Client;
}

function sanitizeFileName(fileName: string): string {
  const base = fileName.split(/[\\/]/).at(-1) ?? "upload.bin";
  const normalized = base
    .normalize("NFKD")
    .replace(/[^\w.\-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");

  if (!normalized) {
    return "upload.bin";
  }

  return normalized.slice(0, 120);
}

export function getUploadConfigStatus(): UploadConfigStatus {
  const region = readEnv("AWS_REGION");
  const bucket = readEnv("S3_BUCKET");
  const accessKeyId = readEnv("AWS_ACCESS_KEY_ID");
  const secretAccessKey = readEnv("AWS_SECRET_ACCESS_KEY");

  const missing: string[] = [];
  if (!region) {
    missing.push("AWS_REGION");
  }
  if (!bucket) {
    missing.push("S3_BUCKET");
  }
  if (!accessKeyId) {
    missing.push("AWS_ACCESS_KEY_ID");
  }
  if (!secretAccessKey) {
    missing.push("AWS_SECRET_ACCESS_KEY");
  }

  if (missing.length > 0 || !region || !bucket || !accessKeyId || !secretAccessKey) {
    return { configured: false, missing };
  }

  return {
    configured: true,
    config: {
      region,
      bucket,
      accessKeyId,
      secretAccessKey
    }
  };
}

function buildUploadKey(caseId: string, fileName: string): string {
  const safeName = sanitizeFileName(fileName);
  const stamp = new Date().toISOString().slice(0, 10);
  return `cases/${caseId}/assets/${stamp}/${randomUUID()}-${safeName}`;
}

export async function createUploadPlan(input: CreateUploadPlanInput): Promise<CreateUploadPlanResult> {
  const configStatus = getUploadConfigStatus();
  if (!configStatus.configured) {
    throw new Error(`Missing upload config: ${configStatus.missing.join(", ")}`);
  }

  const s3Key = buildUploadKey(input.caseId, input.fileName);
  const command = new PutObjectCommand({
    Bucket: configStatus.config.bucket,
    Key: s3Key,
    ContentType: input.mimeType
  });

  const uploadUrl = await getSignedUrl(getS3Client(configStatus.config), command, {
    expiresIn: PRESIGNED_URL_TTL_SECONDS
  });

  return {
    s3Key,
    uploadUrl,
    expiresInSeconds: PRESIGNED_URL_TTL_SECONDS
  };
}

export async function createDownloadPlan(
  input: CreateDownloadPlanInput
): Promise<CreateDownloadPlanResult> {
  const configStatus = getUploadConfigStatus();
  if (!configStatus.configured) {
    throw new Error(`Missing upload config: ${configStatus.missing.join(", ")}`);
  }

  const command = new GetObjectCommand({
    Bucket: configStatus.config.bucket,
    Key: input.s3Key,
    ResponseContentDisposition: input.fileName
      ? `${input.disposition === "attachment" ? "attachment" : "inline"}; filename="${sanitizeFileName(input.fileName)}"`
      : undefined
  });

  const downloadUrl = await getSignedUrl(getS3Client(configStatus.config), command, {
    expiresIn: PRESIGNED_DOWNLOAD_TTL_SECONDS
  });

  return {
    downloadUrl,
    expiresInSeconds: PRESIGNED_DOWNLOAD_TTL_SECONDS
  };
}
