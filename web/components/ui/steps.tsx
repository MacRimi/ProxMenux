import React from "react"

interface StepProps {
  title: string
  children: React.ReactNode
}

const Step: React.FC<StepProps> = ({ title, children }) => (
  <div className="mb-10 last:mb-0">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
      {/* placeholder — actual badge content injected by Steps wrapper below */}
      <h3 className="text-xl font-semibold text-gray-900 m-0">{title}</h3>
    </div>
    <div className="text-gray-800">{children}</div>
  </div>
)

interface StepsProps {
  children: React.ReactNode
}

const Steps: React.FC<StepsProps> & { Step: typeof Step } = ({ children }) => {
  const items = React.Children.toArray(children).filter(React.isValidElement)
  return (
    <div className="my-6 space-y-0">
      {items.map((child, index) => {
        // We expect each child to be a <Steps.Step>; inject the Step N badge
        // before its title. We rebuild the child so the rendering stays self
        // contained inside Steps — callers don't need to pass the number.
        const element = child as React.ReactElement<StepProps>
        return (
          <div key={index} className="mb-10 last:mb-0">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
              <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
                Step {index + 1}
              </span>
              <h3 className="text-xl font-semibold text-gray-900 m-0">
                {element.props.title}
              </h3>
            </div>
            <div className="text-gray-800">{element.props.children}</div>
          </div>
        )
      })}
    </div>
  )
}

Steps.Step = Step

export { Steps }
