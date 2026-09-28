import { useId, type ReactNode } from "react";

type Props = {
  label: string;
  /** Receives the id to put on the control. */
  children: (id: string) => ReactNode;
};

/** Label tied to its control by id. A label wrapping a <select> would make
 * browsers read the selected option as part of the field's name. */
export function Field({ label, children }: Props) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
    </div>
  );
}
