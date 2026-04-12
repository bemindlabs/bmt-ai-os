"use client";

import React, { useState, useRef } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Database, FolderOpen, Network, NotebookPen, Search } from "lucide-react";
import { FileManagerClient } from "../files/file-manager-client";
import { PersonaSelector, useActivePersona } from "./persona-selector";
import { personaFilesPath } from "./helpers";
import { CollectionsTab } from "./collections-tab";
import { IngestTab } from "./ingest-tab";
import { SearchTab } from "./search-tab";
import { NotesTab } from "./notes-tab";
import { GraphTab } from "./graph-tab";

export default function KnowledgePage() {
  const { activePersona, workspacePath, setPersona } = useActivePersona();

  // Controlled tab state — needed so GraphTab can navigate to Notes tab
  const [activeTab, setActiveTab] = useState("files");

  // Path pre-selected from graph navigation (passed to NotesTab)
  const pendingNotePathRef = useRef<string | null>(null);

  function handleOpenNoteFromGraph(notePath: string) {
    pendingNotePathRef.current = notePath;
    setActiveTab("notes");
  }

  return (
    <div className="flex h-full flex-col space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <div>
          <h1 className="text-xl font-semibold">Knowledge & Files</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Browse device files, manage RAG collections, ingest documents, and search the vector store.
          </p>
        </div>

        {/* Persona selector row */}
        <PersonaSelector
          activePersona={activePersona}
          onPersonaChange={setPersona}
        />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as string)}
        className="flex flex-1 flex-col min-h-0"
      >
        <TabsList>
          <TabsTrigger value="files">
            <FolderOpen className="mr-1.5 size-4" />
            Files
          </TabsTrigger>
          <TabsTrigger value="collections">
            <Database className="mr-1.5 size-4" />
            Collections
          </TabsTrigger>
          <TabsTrigger value="ingest">
            <FolderOpen className="mr-1.5 size-4" />
            Ingest
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="mr-1.5 size-4" />
            Search
          </TabsTrigger>
          <TabsTrigger value="notes">
            <NotebookPen className="mr-1.5 size-4" />
            Notes
          </TabsTrigger>
          <TabsTrigger value="graph">
            <Network className="mr-1.5 size-4" />
            Graph
          </TabsTrigger>
        </TabsList>

        <TabsContent value="files" className="mt-4 flex flex-1 min-h-0">
          <FileManagerClient
            initialPath={
              activePersona
                ? personaFilesPath(activePersona, workspacePath)
                : undefined
            }
          />
        </TabsContent>

        <TabsContent value="collections" className="mt-4">
          <CollectionsTab activePersona={activePersona} />
        </TabsContent>

        <TabsContent value="ingest" className="mt-4">
          <IngestTab
            activePersona={activePersona}
            personaWorkspacePath={workspacePath}
          />
        </TabsContent>

        <TabsContent value="search" className="mt-4">
          <SearchTab activePersona={activePersona} />
        </TabsContent>

        <TabsContent value="notes" className="mt-4 flex flex-1 min-h-0">
          <NotesTab
            activePersona={activePersona}
            workspacePath={workspacePath}
            pendingNotePathRef={pendingNotePathRef}
          />
        </TabsContent>

        <TabsContent value="graph" className="mt-4 flex flex-1 min-h-0">
          <GraphTab
            activePersona={activePersona}
            workspacePath={workspacePath}
            onOpenNote={handleOpenNoteFromGraph}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
