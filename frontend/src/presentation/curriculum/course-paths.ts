/** Where the authoring turns are told to write, mirrored for the links back.
 *
 * **A second copy of two strings the server owns** (`course_authoring.py`'s
 * `AREAS_DIR` and `PATHS_DIR`), and the duplication is deliberate rather than
 * overlooked. The alternative is putting the path of every written file on the
 * authoring frame, which means the server enumerating a workspace it does not
 * read in order to tell the client something the client can construct.
 *
 * What it costs: a rename on the server that is not made here produces a dead
 * link rather than an error. That is the failure to watch for, and it is why
 * these live in one named module instead of inline at the two call sites --
 * one place to grep when the server side moves.
 */

export const AREAS_DIR = '/course/areas'
export const PATHS_DIR = '/course/paths'
