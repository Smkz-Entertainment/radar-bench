# Historical artifacts

The five decisive historical bundles are RECONSTRUCT_ONLY. The repository
publishes their manifests, expected internal filenames, sizes, SHA-256 digests,
bundle digests, upstream provenance, supported architecture, and reconstruction
recipe. It does not redistribute third-party wheel bytes.

The acquisition pipeline is:

    approved metadata
      -> final-URL host validation
      -> exact filename selection
      -> bounded download
      -> size and SHA-256 verification
      -> archive traversal and CRC validation
      -> exact bundle inventory validation
      -> runtime reconstruction

Only the artifact acquisition phase may use the network. Historical evaluation
is a separate network-denied Docker phase. Artifact reproducibility therefore
does not imply execution reproducibility, and execution reproducibility does
not imply that the frozen investigator succeeded scientifically.

If redistribution rights are unclear, publish a deterministic reconstruction
recipe and hashes instead of uploading bytes. The catalog keeps the
redistribution status explicit.
