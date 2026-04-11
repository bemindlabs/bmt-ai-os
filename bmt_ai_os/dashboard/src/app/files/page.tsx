import { FileManagerClient } from "./file-manager-client";

export default function FilesPage() {
  return (
    <div className="flex h-full flex-col space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Files</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Browse, preview, upload and ingest files into the RAG knowledge base.
        </p>
      </div>
      <FileManagerClient />
    </div>
  );
}
