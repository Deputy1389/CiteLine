import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import vision from "@google-cloud/vision";
import { createHash } from "node:crypto";
import { Readable } from "node:stream";
import pdfParse from "pdf-parse";

const { ImageAnnotatorClient } = vision;

type OcrCacheLookupInput = {
  contentSha256: string;
  fileName: string;
  mimeType: string;
};

type OcrCacheLookupResult = {
  sourceExtractionId: string;
  engine: string;
  engineVersion?: string;
  rawText: string;
  structuredFacts: Record<string, unknown>;
  pageUnitEstimate?: number;
};

export type OcrInput = {
  assetId: string;
  caseId: string;
  s3Key: string;
  fileName: string;
  mimeType: string;
  userDescription?: string;
  cacheLookup?: (input: OcrCacheLookupInput) => Promise<OcrCacheLookupResult | null>;
};

export type OcrResult = {
  engine: string;
  engineVersion?: string;
  rawText: string;
  structuredFacts: Record<string, unknown>;
  providerMetadata?: Record<string, unknown>;
  sourceMetadata?: Record<string, unknown>;
};

export interface OcrProvider {
  run(input: OcrInput): Promise<OcrResult>;
}

type OcrProviderName = "stub" | "google_vision";

type GoogleVisionSymbol = {
  text?: string | null;
};

type GoogleVisionWord = {
  symbols?: GoogleVisionSymbol[] | null;
};

type GoogleVisionParagraph = {
  words?: GoogleVisionWord[] | null;
};

type GoogleVisionBlock = {
  paragraphs?: GoogleVisionParagraph[] | null;
};

type GoogleVisionPage = {
  width?: number | null;
  height?: number | null;
  confidence?: number | null;
  blocks?: GoogleVisionBlock[] | null;
};

export type GoogleVisionDocumentResponse = {
  fullTextAnnotation?: {
    text?: string | null;
    pages?: GoogleVisionPage[] | null;
  } | null;
  textAnnotations?: Array<{ description?: string | null }> | null;
};

type S3ObjectReadResult = {
  bytes: Uint8Array;
  sourceMetadata: Record<string, unknown>;
};

type FetchS3ObjectFn = (input: { bucket: string; key: string }) => Promise<S3ObjectReadResult>;
type RunGoogleVisionFn = (input: { content: Uint8Array; mimeType: string }) => Promise<GoogleVisionDocumentResponse>;

export type GoogleVisionOcrProviderDeps = {
  bucket?: string;
  fetchS3Object?: FetchS3ObjectFn;
  runGoogleVision?: RunGoogleVisionFn;
  engineVersion?: string;
};

export type OcrProviderFactoryOptions = {
  provider?: string;
  googleVisionFactory?: () => OcrProvider;
};

class DeterministicStubOcrProvider implements OcrProvider {
  async run(input: OcrInput): Promise<OcrResult> {
    const rawText = [
      "CLEARCASE OCR STUB OUTPUT",
      `CASE: ${input.caseId}`,
      `ASSET: ${input.assetId}`,
      `FILE: ${input.fileName}`,
      `MIME: ${input.mimeType}`,
      input.userDescription ? `USER_CONTEXT: ${input.userDescription}` : null
    ]
      .filter((line): line is string => typeof line === "string")
      .join("\n");

    return {
      engine: "stub-deterministic-ocr",
      engineVersion: "v1",
      rawText,
      structuredFacts: {
        source: "deterministic_stub",
        fileName: input.fileName,
        mimeType: input.mimeType,
        userDescription: input.userDescription ?? null
      },
      providerMetadata: {
        provider: "stub",
        mode: "deterministic"
      },
      sourceMetadata: {
        location: "in_memory_stub"
      }
    };
  }
}

let cachedS3Client: S3Client | null = null;
let cachedS3Region = "";
let cachedVisionClient: InstanceType<typeof ImageAnnotatorClient> | null = null;

function readRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function normalizeProvider(rawValue: string | undefined): OcrProviderName | null {
  const value = rawValue?.trim().toLowerCase();
  if (!value || value === "stub") return "stub";
  if (value === "google_vision") return "google_vision";
  return null;
}

function getS3Client(region: string): S3Client {
  if (cachedS3Client && cachedS3Region === region) {
    return cachedS3Client;
  }

  const accessKeyId = process.env.AWS_ACCESS_KEY_ID?.trim();
  const secretAccessKey = process.env.AWS_SECRET_ACCESS_KEY?.trim();
  const sessionToken = process.env.AWS_SESSION_TOKEN?.trim();

  cachedS3Client = new S3Client({
    region,
    credentials:
      accessKeyId && secretAccessKey
        ? {
            accessKeyId,
            secretAccessKey,
            sessionToken: sessionToken || undefined
          }
        : undefined
  });
  cachedS3Region = region;
  return cachedS3Client;
}

function getVisionClient(): InstanceType<typeof ImageAnnotatorClient> {
  if (cachedVisionClient) return cachedVisionClient;
  cachedVisionClient = new ImageAnnotatorClient();
  return cachedVisionClient;
}

async function bodyToByteArray(body: unknown): Promise<Uint8Array> {
  if (!body) return new Uint8Array();
  if (body instanceof Uint8Array) return body;
  if (Buffer.isBuffer(body)) return new Uint8Array(body);

  if (typeof body === "object" && body !== null) {
    const maybeTransform = body as { transformToByteArray?: () => Promise<Uint8Array> };
    if (typeof maybeTransform.transformToByteArray === "function") {
      return maybeTransform.transformToByteArray();
    }
  }

  const readable = body as Readable;
  if (readable instanceof Readable || typeof (body as { [Symbol.asyncIterator]?: unknown })[Symbol.asyncIterator] === "function") {
    const chunks: Buffer[] = [];
    for await (const chunk of readable as AsyncIterable<unknown>) {
      if (typeof chunk === "string") {
        chunks.push(Buffer.from(chunk));
      } else if (chunk instanceof Uint8Array) {
        chunks.push(Buffer.from(chunk));
      } else {
        chunks.push(Buffer.from(String(chunk)));
      }
    }
    return new Uint8Array(Buffer.concat(chunks));
  }

  throw new Error("Unable to convert S3 body stream to bytes.");
}

async function defaultFetchS3Object(input: { bucket: string; key: string }): Promise<S3ObjectReadResult> {
  const region = readRequiredEnv("AWS_REGION");
  const client = getS3Client(region);
  const response = await client.send(
    new GetObjectCommand({
      Bucket: input.bucket,
      Key: input.key
    })
  );

  const bytes = await bodyToByteArray(response.Body);
  return {
    bytes,
    sourceMetadata: {
      bucket: input.bucket,
      s3Key: input.key,
      contentLength: response.ContentLength ?? bytes.byteLength,
      etag: response.ETag ?? null,
      lastModified: response.LastModified?.toISOString() ?? null
    }
  };
}

async function defaultRunGoogleVision(input: {
  content: Uint8Array;
  mimeType: string;
}): Promise<GoogleVisionDocumentResponse> {
  const client = getVisionClient();
  const [response] = await client.documentTextDetection({
    image: {
      content: Buffer.from(input.content)
    }
  });
  return response as unknown as GoogleVisionDocumentResponse;
}

function extractRawText(annotation: GoogleVisionDocumentResponse): string {
  const primary = annotation.fullTextAnnotation?.text?.trim();
  if (primary) return primary;
  const fallback = annotation.textAnnotations?.[0]?.description?.trim();
  return fallback ?? "";
}

function normalizeExtractedText(value: string): string {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isPdfMimeType(mimeType: string): boolean {
  return mimeType.trim().toLowerCase().includes("pdf");
}

function hasMeaningfulEmbeddedPdfText(text: string): boolean {
  if (!text.trim()) return false;
  const compact = text.replace(/\s+/g, " ").trim();
  if (compact.length < 40) return false;
  return /[A-Za-z0-9]/.test(compact);
}

type PdfTextProbe = {
  text: string;
  pageCount: number;
  meaningful: boolean;
  parseError: string | null;
};

async function probeEmbeddedPdfText(bytes: Uint8Array): Promise<PdfTextProbe> {
  try {
    const parsed = await pdfParse(Buffer.from(bytes));
    const text = normalizeExtractedText(parsed.text ?? "");
    const pageCount =
      Number.isFinite(parsed.numpages) && parsed.numpages > 0 ? Math.floor(parsed.numpages) : 1;
    return {
      text,
      pageCount,
      meaningful: hasMeaningfulEmbeddedPdfText(text),
      parseError: null
    };
  } catch (error) {
    return {
      text: "",
      pageCount: 1,
      meaningful: false,
      parseError: error instanceof Error ? error.message : String(error)
    };
  }
}

function derivePageUnitEstimate(input: {
  mimeType: string;
  pdfProbe: PdfTextProbe | null;
  visionPageCount: number;
}): number {
  if (input.pdfProbe && input.pdfProbe.pageCount > 0) {
    return input.pdfProbe.pageCount;
  }
  if (input.visionPageCount > 0) {
    return input.visionPageCount;
  }
  if (isPdfMimeType(input.mimeType)) {
    return 1;
  }
  return 1;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function summarizeVisionPage(page: GoogleVisionPage, index: number): Record<string, unknown> {
  const blocks = page.blocks ?? [];
  let paragraphCount = 0;
  let wordCount = 0;
  let symbolCount = 0;

  for (const block of blocks) {
    const paragraphs = block.paragraphs ?? [];
    paragraphCount += paragraphs.length;
    for (const paragraph of paragraphs) {
      const words = paragraph.words ?? [];
      wordCount += words.length;
      for (const word of words) {
        symbolCount += word.symbols?.length ?? 0;
      }
    }
  }

  return {
    pageNumber: index + 1,
    width: page.width ?? null,
    height: page.height ?? null,
    confidence: page.confidence ?? null,
    blockCount: blocks.length,
    paragraphCount,
    wordCount,
    symbolCount
  };
}

class GoogleVisionOcrProvider implements OcrProvider {
  private readonly bucket: string;
  private readonly fetchS3Object: FetchS3ObjectFn;
  private readonly runGoogleVision: RunGoogleVisionFn;
  private readonly engineVersion: string;

  constructor(deps: GoogleVisionOcrProviderDeps = {}) {
    this.bucket = deps.bucket ?? readRequiredEnv("S3_BUCKET");
    this.fetchS3Object = deps.fetchS3Object ?? defaultFetchS3Object;
    this.runGoogleVision = deps.runGoogleVision ?? defaultRunGoogleVision;
    this.engineVersion = deps.engineVersion ?? "v1-document_text_detection";
  }

  async run(input: OcrInput): Promise<OcrResult> {
    const s3Object = await this.fetchS3Object({
      bucket: this.bucket,
      key: input.s3Key
    });
    const contentSha256 = createHash("sha256")
      .update(Buffer.from(s3Object.bytes))
      .digest("hex");

    const baseSourceMetadata = {
      ...s3Object.sourceMetadata,
      fileName: input.fileName,
      mimeType: input.mimeType,
      objectByteLength: s3Object.bytes.byteLength,
      contentSha256
    };

    const pdfProbe = isPdfMimeType(input.mimeType)
      ? await probeEmbeddedPdfText(s3Object.bytes)
      : null;

    const cacheHit = input.cacheLookup
      ? await input.cacheLookup({
          contentSha256,
          fileName: input.fileName,
          mimeType: input.mimeType
        })
      : null;

    if (cacheHit) {
      const pageUnitEstimate =
        cacheHit.pageUnitEstimate ??
        derivePageUnitEstimate({
          mimeType: input.mimeType,
          pdfProbe,
          visionPageCount: 0
        });
      const cachedStructuredFacts = asRecord(cacheHit.structuredFacts) ?? {
        source: "cache_reused_structured_facts"
      };

      const providerMetadata = {
        provider: "cache",
        mode: "same_user_content_hash_reuse",
        processingPath: "cache_reuse",
        cache: {
          hit: true,
          sourceExtractionId: cacheHit.sourceExtractionId
        },
        pageUnitEstimate
      };

      return {
        engine: cacheHit.engine,
        engineVersion: cacheHit.engineVersion ?? this.engineVersion,
        rawText: cacheHit.rawText,
        structuredFacts: {
          ...cachedStructuredFacts,
          sourceMetadata: baseSourceMetadata,
          providerMetadata,
          cacheReuse: {
            sourceExtractionId: cacheHit.sourceExtractionId
          }
        },
        providerMetadata,
        sourceMetadata: baseSourceMetadata
      };
    }

    if (pdfProbe?.meaningful) {
      const pageUnitEstimate = derivePageUnitEstimate({
        mimeType: input.mimeType,
        pdfProbe,
        visionPageCount: 0
      });

      const providerMetadata = {
        provider: "pdf_text_direct",
        mode: "embedded_text_extraction",
        processingPath: "pdf_text_direct",
        cache: {
          hit: false,
          sourceExtractionId: null
        },
        pageCount: pdfProbe.pageCount,
        textLength: pdfProbe.text.length,
        pageUnitEstimate
      };

      return {
        engine: "pdf-text-direct",
        engineVersion: "v1-embedded-text",
        rawText: pdfProbe.text,
        structuredFacts: {
          source: "pdf_text_direct",
          fileName: input.fileName,
          mimeType: input.mimeType,
          userDescription: input.userDescription ?? null,
          sourceMetadata: baseSourceMetadata,
          providerMetadata,
          pdfDirectText: {
            pageCount: pdfProbe.pageCount,
            meaningfulTextDetected: true
          }
        },
        providerMetadata,
        sourceMetadata: baseSourceMetadata
      };
    }

    const annotation = await this.runGoogleVision({
      content: s3Object.bytes,
      mimeType: input.mimeType
    });
    const rawText = extractRawText(annotation);
    const pages = annotation.fullTextAnnotation?.pages ?? [];
    const pageSummaries = pages.map((page, index) => summarizeVisionPage(page, index));
    const pageUnitEstimate = derivePageUnitEstimate({
      mimeType: input.mimeType,
      pdfProbe,
      visionPageCount: pageSummaries.length
    });

    const providerMetadata = {
      provider: "google_vision",
      mode: "document_text_detection",
      engineVersion: this.engineVersion,
      processingPath: "google_vision",
      textLength: rawText.length,
      pageCount: pageSummaries.length,
      pageUnitEstimate,
      cache: {
        hit: false,
        sourceExtractionId: null
      },
      pdfTextProbe: pdfProbe
        ? {
            meaningfulTextDetected: pdfProbe.meaningful,
            extractedTextLength: pdfProbe.text.length,
            pageCount: pdfProbe.pageCount,
            scannedPageOnlyOcrApplied: false,
            scannedPageOnlyOcrLimitation:
              "page_level_split_ocr_not_implemented_full_document_ocr_fallback",
            parseError: pdfProbe.parseError
          }
        : null
    };

    return {
      engine: "google-vision-document-ocr",
      engineVersion: this.engineVersion,
      rawText,
      structuredFacts: {
        source: "google_vision_document_text_detection",
        fileName: input.fileName,
        mimeType: input.mimeType,
        userDescription: input.userDescription ?? null,
        sourceMetadata: baseSourceMetadata,
        providerMetadata,
        pageSummaries
      },
      providerMetadata,
      sourceMetadata: baseSourceMetadata
    };
  }
}

export function createGoogleVisionOcrProvider(deps: GoogleVisionOcrProviderDeps = {}): OcrProvider {
  return new GoogleVisionOcrProvider(deps);
}

export function createOcrProvider(options: OcrProviderFactoryOptions = {}): OcrProvider {
  const normalized = normalizeProvider(options.provider ?? process.env.OCR_PROVIDER);
  if (!normalized) {
    const value = options.provider ?? process.env.OCR_PROVIDER ?? "";
    throw new Error(
      `Unsupported OCR_PROVIDER='${value}'. Supported values: stub, google_vision.`
    );
  }

  if (normalized === "stub") {
    return new DeterministicStubOcrProvider();
  }

  if (options.googleVisionFactory) {
    return options.googleVisionFactory();
  }
  return createGoogleVisionOcrProvider();
}
